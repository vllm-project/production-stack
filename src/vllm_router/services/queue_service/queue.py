# services/queue_manager.py

import asyncio
from typing import Dict, Any, Tuple
from vllm_router.stats.engine_stats import EngineStatsScraper

class EndpointQueueManager:
    def __init__(self):
        self.endpoint_queues: Dict[str, asyncio.PriorityQueue] = {}
        self.queue_tasks: Dict[str, asyncio.Task] = {}
        self.scraper = EngineStatsScraper(scrape_interval=5)

    def get_queue(self, endpoint_url: str) -> asyncio.PriorityQueue:
        if endpoint_url not in self.endpoint_queues:
            self.endpoint_queues[endpoint_url] = asyncio.PriorityQueue()
        return self.endpoint_queues[endpoint_url]

    async def enqueue(
        self, endpoint_url: str, request: Dict[str, Any], priority: int = 0
    ):
        queue = self.get_queue(endpoint_url)
        await queue.put((priority, request))

    def start_scheduler_for(self, endpoint_url: str):
        if endpoint_url not in self.queue_tasks:
            queue = self.get_queue(endpoint_url)
            self.queue_tasks[endpoint_url] = asyncio.create_task(
                self._scheduler_loop(endpoint_url, queue)
            )

    async def _scheduler_loop(self, endpoint_url: str, queue: asyncio.PriorityQueue):
        while True:
            await self._wait_for_endpoint_to_be_free(endpoint_url)

            try:
                # Only dequeue if a request is waiting
                priority, request = queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)
                continue

            await self.dispatch_request(endpoint_url, request)

    async def _wait_for_endpoint_to_be_free(self, endpoint_url: str):
        """
        Wait until endpoint has capacity to handle a new request.
        """
        while True:
            stats = self.scraper.get_engine_stats().get(endpoint_url)
            if stats and stats.num_running_requests < 4 and stats.gpu_cache_usage_perc < 90:
                return
            await asyncio.sleep(0.2)

    async def dispatch_request(self, endpoint_url: str, req: Dict[str, Any]):
        from vllm_router.services.request_service.request import process_request

        try:
            await process_request(
                req["request"], req["body"], endpoint_url,
                req["request_id"], req["endpoint"], req["background_tasks"]
            )
        except Exception as e:
            print(f"[Queue Dispatch Error] {e}")

    def get_queue_length(self, endpoint_url: str) -> int:
        return self.get_queue(endpoint_url).qsize()

    def stop_scheduler(self, endpoint_url: str):
        if endpoint_url in self.queue_tasks:
            self.queue_tasks[endpoint_url].cancel()
            del self.queue_tasks[endpoint_url]

    @staticmethod
    def calculate_request_priority(request) -> int:
        return 0
    
queue_manager = EndpointQueueManager()