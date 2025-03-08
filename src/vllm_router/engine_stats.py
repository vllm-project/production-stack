import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests
from prometheus_client.parser import text_string_to_metric_families

from vllm_router.log import init_logger
from vllm_router.service_discovery import GetServiceDiscovery

logger = init_logger(__name__)


class SingletonMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


@dataclass
class EngineStats:
    # Number of running requests
    num_running_requests: int = 0
    # Number of queuing requests
    num_queuing_requests: int = 0
    # GPU prefix cache hit rate (as used in some panels)
    gpu_prefix_cache_hit_rate: float = 0.0
    # GPU KV usage percentage (new field for dashboard "GPU KV Usage Percentage")
    gpu_cache_usage_perc: float = 0.0

    @staticmethod
    def FromVllmScrape(vllm_scrape: str):
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
                    num_running_reqs = sample.value
                elif sample.name == "vllm:num_requests_waiting":
                    num_queuing_reqs = sample.value
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
    def __init__(self, scrape_interval: float):
        """
        Initialize the scraper to periodically fetch metrics from all serving engines.

        Args:
            scrape_interval (float): The interval in seconds
                to scrape the metrics.

        Raises:
            ValueError: if the service discover module is have
            not been initialized.

        """
        # Allow multiple calls but require the first call provide scrape_interval.
        if hasattr(self, "_initialized"):
            return
        if scrape_interval is None:
            raise ValueError(
                "EngineStatsScraper must be initialized with scrape_interval"
            )
        self.service_discovery = GetServiceDiscovery()  # (remains unchanged)
        self.engine_stats: Dict[str, EngineStats] = {}
        self.engine_stats_lock = threading.Lock()
        self.scrape_interval = scrape_interval
        self.scrape_thread = threading.Thread(target=self._scrape_worker, daemon=True)
        self.scrape_thread.start()
        self._initialized = True

    def _scrape_one_endpoint(self, url: str):
        """
        Scrape metrics from a single serving engine.

        Args:
            url (str): The URL of the serving engine (does not contain endpoint)
        """
        try:
            response = requests.get(url + "/metrics")
            response.raise_for_status()
            engine_stats = EngineStats.FromVllmScrape(response.text)
        except Exception as e:
            logger.error(f"Failed to scrape metrics from {url}: {e}")
            return None
        return engine_stats

    def _scrape_metrics(self):
        """
        Scrape metrics from all serving engines.

        Scrape metrics from all serving engines by calling
        _scrape_one_endpoint on each of them. The metrics are
        stored in self.engine_stats.

        """
        collected_engine_stats = {}
        endpoints = self.service_discovery.get_endpoint_info()
        logger.info(f"Scraping metrics from {len(endpoints)} serving engine(s)")
        for info in endpoints:
            url = info.url
            engine_stats = self._scrape_one_endpoint(url)
            if engine_stats:
                collected_engine_stats[url] = engine_stats

        with self.engine_stats_lock:
            old_urls = list(self.engine_stats.keys())
            for old_url in old_urls:
                if old_url not in collected_engine_stats:
                    del self.engine_stats[old_url]
            for url, stats in collected_engine_stats.items():
                self.engine_stats[url] = stats

    def _scrape_worker(self):
        """
        Periodically scrape metrics from all serving engines in the background.

        This function will loop forever and sleep for self.scrape_interval
        seconds between each scrape. It will call _scrape_metrics to scrape
        metrics from all serving engines and store them in self.engine_stats.

        """
        while True:
            self._scrape_metrics()
            time.sleep(self.scrape_interval)

    def get_engine_stats(self) -> Dict[str, EngineStats]:
        """
        Retrieve a copy of the current engine statistics.

        Returns:
            A dictionary mapping engine URLs to their respective EngineStats objects.
        """
        with self.engine_stats_lock:
            return self.engine_stats.copy()

    def get_health(self) -> bool:
        """
        Check if the EngineStatsScraper is healthy

        Returns:
            bool: True if the EngineStatsScraper is healthy,
                False otherwise
        """
        return self.scrape_thread.is_alive()


def InitializeEngineStatsScraper(scrape_interval: float) -> EngineStatsScraper:
    return EngineStatsScraper(scrape_interval)


def GetEngineStatsScraper() -> EngineStatsScraper:
    # This call returns the already-initialized instance (or raises an error if not yet initialized)
    return EngineStatsScraper()
