import asyncio
import threading
from dataclasses import dataclass
from typing import Dict, Set

import aiohttp
from prometheus_client.parser import text_string_to_metric_families

from vllm_router.log import init_logger
from vllm_router.service_discovery import get_service_discovery
from vllm_router.utils import SingletonMeta

logger = init_logger(__name__)


@dataclass
class EngineStats:
    # Number of running requests
    num_running_requests: int = 0
    # Number of queuing requests
    num_queuing_requests: int = 0
    # GPU prefix cache hit rate (as used in some panels)
    gpu_prefix_cache_hit_rate: float = 0.0
    # GPU KV usage percentage (new field for dashboard)
    gpu_cache_usage_perc: float = 0.0

    @staticmethod
    def from_vllm_scrape(vllm_scrape: str):
        """
        Parse the vllm scrape string and return a EngineStats object

        Args:
            vllm_scrape (str): The vllm scrape string

        Returns:
            EngineStats: The EngineStats object

        Note:
            Assume vllm only runs a single model
        """
        num_running_reqs = 0
        num_queuing_reqs = 0
        gpu_prefix_cache_hit_rate = 0.0
        gpu_cache_usage_perc = 0.0

        for family in text_string_to_metric_families(vllm_scrape):
            for sample in family.samples:
                if sample.name == "vllm:num_requests_running":
                    num_running_reqs = int(sample.value)
                elif sample.name == "vllm:num_requests_waiting":
                    num_queuing_reqs = int(sample.value)
                elif sample.name == "vllm:gpu_prefix_cache_hit_rate":
                    gpu_prefix_cache_hit_rate = sample.value
                elif sample.name == "vllm:gpu_cache_usage_perc":
                    gpu_cache_usage_perc = sample.value

        return EngineStats(
            num_running_requests=num_running_reqs,
            num_queuing_requests=num_queuing_reqs,
            gpu_prefix_cache_hit_rate=gpu_prefix_cache_hit_rate,
            gpu_cache_usage_perc=gpu_cache_usage_perc,
        )


class EngineStatsScraper(metaclass=SingletonMeta):
    def __init__(self, scrape_interval: float = None):
        """
        Initialize the scraper to fetch metrics from serving engines.

        Args:
            scrape_interval (float): The interval in seconds
                to scrape the metrics.

        Raises:
            ValueError: if the service discover module is have
            not been initialized.
        """
        # Allow multiple calls but require the first call provide scrape_interval
        if hasattr(self, "_initialized"):
            return
        if scrape_interval is None:
            raise ValueError("EngineStatsScraper must be initialized with scrape_interval")
        # Store engine stats by URL
        self.engine_stats: Dict[str, EngineStats] = {}
        self.engine_stats_lock = threading.Lock()
        self.scrape_interval = scrape_interval

        # Initialize asyncio
        self.loop = asyncio.new_event_loop()

        # State tracking
        self.running = True
        self.session_initialized = asyncio.Event()

        # Start the event loop thread
        self.event_loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.event_loop_thread.start()

        # Initialize aiohttp session
        future = asyncio.run_coroutine_threadsafe(self._init_session(), self.loop)
        # Wait for session to be initialized
        future.result(timeout=5)

        # Start the scrape cycle
        self._start_scraping()
        self._initialized = True

    def _run_event_loop(self):
        """Run the asyncio event loop in its own thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _init_session(self):
        """Initialize aiohttp session."""
        self.aiohttp_session = aiohttp.ClientSession()
        self.session_initialized.set()

    def _start_scraping(self):
        """Start the periodic scraping task."""
        asyncio.run_coroutine_threadsafe(self._periodic_scrape(), self.loop)

    async def _scrape_one_endpoint(self, url: str, scraped_urls: Set[str]):
        """
        Scrape metrics from a single serving engine asynchronously.

        Args:
            url: The URL of the serving engine
            scraped_urls: Set of already scraped URLs

        Returns:
            A tuple of (stats, url) where stats is an EngineStats object or None if scraping failed
        """
        if url in scraped_urls:
            return None, url

        try:
            # Wait for session to be initialized
            await self.session_initialized.wait()

            # Use a shorter timeout to avoid blocking health checks
            timeout = aiohttp.ClientTimeout(total=self.scrape_interval / 2, connect=1, sock_read=2)
            metrics_url = f"{url}/metrics"

            async with self.aiohttp_session.get(metrics_url, timeout=timeout) as response:
                response.raise_for_status()
                text = await response.text()
                stats = EngineStats.from_vllm_scrape(text)
                scraped_urls.add(url)
                return stats, url

        except asyncio.TimeoutError:
            logger.warning(f"Timeout when scraping metrics from {url}")
            return None, url
        except aiohttp.ClientConnectorError as e:
            logger.warning(f"Connection error when scraping metrics from {url}: {e}")
            # Report to service discovery that this endpoint might be unhealthy
            try:
                service_discovery = get_service_discovery()
                if hasattr(service_discovery, "remove_endpoint_by_url"):
                    service_discovery.remove_endpoint_by_url(url)
                    logger.info(f"Removed unhealthy endpoint {url} from service discovery")
            except Exception as e:
                logger.error(f"Error removing unhealthy endpoint {url}: {e}")
            return None, url
        except aiohttp.ClientResponseError as e:
            logger.warning(f"HTTP error {e.status} when scraping metrics from {url}: {e}")
            return None, url
        except Exception as e:
            logger.error(f"Failed to scrape metrics from {url}: {e}")
            return None, url

    async def _scrape_metrics(self):
        """
        Scrape metrics from all serving engines asynchronously.
        """
        collected_engine_stats = {}
        scraped_urls = set()

        endpoints = get_service_discovery().get_endpoint_info()
        logger.info(f"Scraping metrics from {len(endpoints)} serving engine(s)")

        # Create tasks for all unique endpoints
        unique_urls = {info.url for info in endpoints}

        # Use a task group to ensure all tasks complete or timeout together
        tasks = []
        for url in unique_urls:
            if url not in scraped_urls:
                tasks.append(self._scrape_one_endpoint(url, scraped_urls))

        # Use gather with return_exceptions=True to prevent one failure from cancelling all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process successful results
        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                stats, url = result
                if stats:
                    collected_engine_stats[url] = stats
            elif isinstance(result, Exception):
                logger.warning(f"Exception during metrics scraping: {result}")

        # Update engine_stats dictionary with the collected stats
        with self.engine_stats_lock:
            # Remove URLs that are no longer in collected_engine_stats
            old_urls = list(self.engine_stats.keys())
            for old_url in old_urls:
                if old_url not in collected_engine_stats:
                    del self.engine_stats[old_url]

            # Update with new stats
            for url, stats in collected_engine_stats.items():
                self.engine_stats[url] = stats

    async def _periodic_scrape(self):
        """Periodically scrape metrics from all serving engines."""
        while self.running:
            try:
                await self._scrape_metrics()
            except Exception as e:
                logger.error(f"Error in scrape cycle: {e}")

            # Sleep until next scrape cycle
            await asyncio.sleep(self.scrape_interval)

    def get_engine_stats(self) -> Dict[str, EngineStats]:
        """
        Retrieve a copy of the current engine statistics.

        Returns:
            Dict mapping engine URLs to their stats
        """
        with self.engine_stats_lock:
            return self.engine_stats.copy()

    def get_health(self) -> bool:
        """
        Check if the EngineStatsScraper is healthy

        Returns:
            bool: True if the EngineStatsScraper is healthy
        """
        # Check 1: Is the event loop thread alive?
        if not self.event_loop_thread.is_alive():
            logger.error("EngineStatsScraper unhealthy: Event loop thread is not alive")
            return False

        # Check 2: Was the session initialized successfully?
        if not hasattr(self, "aiohttp_session") or self.aiohttp_session is None:
            logger.error("EngineStatsScraper unhealthy: aiohttp session not initialized")
            return False

        # Everything looks good
        return True

    async def _close_session(self):
        """Close the aiohttp session."""
        if hasattr(self, "aiohttp_session") and self.aiohttp_session:
            await self.aiohttp_session.close()

    def close(self):
        """
        Stop the background tasks and cleanup resources.
        """
        self.running = False

        # Close the aiohttp session
        if hasattr(self, "aiohttp_session"):
            fut = asyncio.run_coroutine_threadsafe(self._close_session(), self.loop)
            try:
                fut.result(timeout=5)
            except:
                logger.warning("Could not close aiohttp session cleanly")

        # Stop the event loop
        if hasattr(self, "loop"):
            self.loop.call_soon_threadsafe(self.loop.stop)

        # Wait for the event loop thread to finish
        if hasattr(self, "event_loop_thread"):
            self.event_loop_thread.join(timeout=5)


def initialize_engine_stats_scraper(scrape_interval: float) -> EngineStatsScraper:
    return EngineStatsScraper(scrape_interval)


def get_engine_stats_scraper() -> EngineStatsScraper:
    # Returns the already-initialized instance
    # It should already be initialized, so we pass None as a placeholder
    return EngineStatsScraper()
