# services/queue_manager.py

import asyncio
import time
from typing import Dict, Any, Tuple
from vllm_router.stats.engine_stats import EngineStatsScraper

class EndpointQueueManager:
    def __init__(self, max_queue_wait_time = 10):
        self.endpoint_queues: Dict[str, asyncio.PriorityQueue] = {}
        self.conditions: Dict[str, asyncio.Condition] = {}

        self.scraper = EngineStatsScraper(scrape_interval=5)
        self.max_queue_wait_time = max_queue_wait_time
        #kept for shutdown
        self.endpoint_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    def register_endpoint(self, endpoint_url: str):
        if endpoint_url in self.endpoint_queues:
            return #already registered
        
        self.endpoint_queues[endpoint_url] = asyncio.PriorityQueue()
        self.conditions[endpoint_url] = asyncio.Condition()
        task = asyncio.create_task(self._scheduler_loop(endpoint_url))
        self.endpoint_tasks[endpoint_url] = task

    async def enqueue(
        self, endpoint_url: str, request: Dict[str, Any], priority: int = 0
    ):
        if self._shutdown_event.is_set():
            raise RuntimeError("Scheduler is shutting down, can't enqueue new requests.")

        await self.endpoint_queues[endpoint_url].put((priority, time.time(). request))
        async with self.conditions[endpoint_url]:
            self.conditions[endpoint_url].notify() #request available in the queue

    async def _scheduler_loop(self, endpoint_url: str):
        queue = self.queues[endpoint_url]
        condition = self.conditions[endpoint_url]

        try:
            while not self._shutdown_event.is_set():
                async with condition:
                    await condition.wait_for(lambda: not queue.empty())

                try:
                    priority, enqueue_time, request = queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue

                wait_duration = time.time() - enqueue_time #stale request logic
                if wait_duration > self.max_queue_wait_time:
                    await self._reroute_or_dispatch_stale_request(request, endpoint_url)
                    continue

                if self._endpoint_is_free(endpoint_url):
                    asyncio.create_task(self._dispatch_and_signal(endpoint_url, request))
                else:
                    await queue.put((priority - 1, enqueue_time, request)) #requeue w higher prio
                    async with condition:
                        await condition.wait()  # only wake up when notified
        
        except asyncio.CancelledError:
            print(f"Scheduler loop for {endpoint_url} cancelled.")
        except Exception as e:
            print(f"Error in scheduler loop ({endpoint_url}): {e}")

    def _endpoint_is_free(self, endpoint_url: str) -> bool: #TODO: what stats?
        """queue waits for endpoint load to decrease before dequeing waiting request"""

        stats = self.scraper.get_engine_stats().get(endpoint_url)
        return stats and stats.num_running_requests < 4 and stats.gpu_cache_usage_perc < 90 #TODO: configurable?

    async def _dispatch_and_signal(self, endpoint_url: str, req: Dict[str, Any]):
        from vllm_router.services.request_service.request import process_request

        try:
            
            stream_generator = process_request(
                req["request"], req["body"], endpoint_url,
                req["request_id"], req["endpoint"], req["background_tasks"]
            )
            headers, status_code = await anext(stream_generator)
            headers_dict = {key: value for key, value in headers.items()}
            headers_dict["X-Request-Id"] = request_id
            return StreamingResponse( #TODO
                stream_generator,
                status_code=status_code,
                headers=headers_dict,
                media_type="text/event-stream",
            )
    
        except Exception as e:
            print(f"[Queue Dispatch Error] {e}")
        finally:
            async with self.conditions[endpoint_url]:
                self.conditions[endpoint_url].notify()


    async def _reroute_or_dispatch_stale_request(self, request: dict, original_endpoint: str):
        request_id = request.get("request_id")
        session_id = request.get("session_id")
        model = request.get("model_name")

        # TODO: Use KV cache hit estimation in future
        has_session_affinity = session_id and self._session_matches_endpoint(session_id, original_endpoint)

        if not has_session_affinity:
            new_endpoint = self.find_best_endpoint(model_name=model, exclude=[original_endpoint])
            if new_endpoint and new_endpoint != original_endpoint:
                print(f"[Rerouting] Request {request_id} → {new_endpoint} (was {original_endpoint})")

                if self._endpoint_is_free(new_endpoint):
                    asyncio.create_task(self._dispatch_and_signal(new_endpoint, request))
                else:
                    queue = self.endpoint_queues[new_endpoint]
                    async with self.conditions[new_endpoint]:
                        await queue.put((self.calculate_request_priority(request), time.time(), request))
                        self.conditions[new_endpoint].notify()
                return

        # Session matches → keep on original endpoint
        print(f"[Requeue] Request {request_id} stays at {original_endpoint}")
        queue = self.endpoint_queues[original_endpoint]
        async with self.conditions[original_endpoint]:
            await queue.put((self.calculate_request_priority(request) - 1, time.time(), request))
            self.conditions[original_endpoint].notify()



    def calculate_request_priority(self, request) -> int:
        return 0
    

    async def shutdown(self):
        print("Shutting down scheduler...")

        self._shutdown_event.set()

        for task in self.endpoint_tasks.values():
            task.cancel()

        # wait for all tasks to cancel
        await asyncio.gather(*self.endpoint_tasks.values(), return_exceptions=True)

        print("Scheduler shutdown complete.")

queue_manager = EndpointQueueManager(max_queue_wait_time = 10)