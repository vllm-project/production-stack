# services/queue_manager.py

import asyncio
import time
from typing import Dict, Any, Optional
from fastapi.responses import StreamingResponse
from vllm_router.stats.engine_stats import get_engine_stats_scraper
from threading import Lock
_global_queue_manager = None

class EndpointQueueManager:
    def __init__(self, max_queue_wait_time, max_running_requests, max_gpu_perc, scraper=None):
        self.endpoint_queues: Dict[str, asyncio.PriorityQueue] = {}
        self.conditions: Dict[str, asyncio.Condition] = {}

        self.scraper = scraper or get_engine_stats_scraper()
        if self.scraper is None:
            raise RuntimeError("Engine stats scraper not initialized.")
        #user configurable
        self.max_running_requests = max_running_requests
        self.max_gpu_perc = max_gpu_perc
        self.max_queue_wait_time = max_queue_wait_time

        #stale request round-robin fallback strategy
        self.req_id = 0
        self._lock = Lock()

        #kept for shutdown
        self.endpoint_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    async def register_endpoint(self, endpoint_url: str):
        if endpoint_url in self.endpoint_queues:
            return #already registered
        
        self.endpoint_queues[endpoint_url] = asyncio.PriorityQueue()
        self.conditions[endpoint_url] = asyncio.Condition()
        task = asyncio.create_task(self._scheduler_loop(endpoint_url))
        self.endpoint_tasks[endpoint_url] = task

    async def enqueue(
        self, endpoint_url: str, request: Dict[str, Any], 
        priority: int = 0
    ):
        if self._shutdown_event.is_set():
            raise RuntimeError("Scheduler is shutting down, can't enqueue new requests.")


        await self.endpoint_queues[endpoint_url].put((priority, time.time(), request))
        async with self.conditions[endpoint_url]:
            self.conditions[endpoint_url].notify() #request available in the queue

    async def _scheduler_loop(self, endpoint_url: str):
        print(f"Scheduler started for {endpoint_url}")

        queue = self.endpoint_queues[endpoint_url]
        condition = self.conditions[endpoint_url]

        try:
            while not self._shutdown_event.is_set():
                async with condition:
                    await condition.wait_for(lambda: not queue.empty())

                try:
                    # Peek at the top of the queue without removing
                    priority, enqueue_time, request = queue._queue[0]
                except IndexError:
                    continue  # queue is empty


                if self._endpoint_is_free(endpoint_url):
                    try:
                        _, _, request = queue.get_nowait()
                        print("Routing request")
                        asyncio.create_task(self._dispatch_and_signal(endpoint_url, request))
                    except Exception as e:
                        print(f"[Dispatch error] {e}")
                    continue
            
                wait_duration = time.time() - enqueue_time
                print(f"Request waited {wait_duration:.2f}s, threshold is {self.max_queue_wait_time}s")
                if wait_duration > self.max_queue_wait_time:
                    # Dequeue and reroute
                    try:
                        _, _, stale_request = queue.get_nowait()
                        await self._reroute_or_dispatch_stale_request(stale_request, endpoint_url)
                    except Exception as e:
                        print(f"[Stale reroute error] {e}")
                    continue
            
                # Endpoint not free and not stale → yield loop
                await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            print(f"Scheduler loop for {endpoint_url} cancelled.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error in scheduler loop ({endpoint_url}): {e}")


    def _endpoint_is_free(self, endpoint_url: str) -> bool: #TODO: what stats could be relevant
        """queue waits for endpoint load to decrease before dequeing waiting request"""

        stats = self.scraper.get_engine_stats().get(endpoint_url)
        return (stats 
                and stats.num_running_requests < self.max_running_requests 
                and stats.gpu_cache_usage_perc < self.max_gpu_perc)

    async def _dispatch_and_signal(self, endpoint_url: str, request: Dict[str, Any]):
        from vllm_router.services.request_service.request import process_request

        result_future = request.get("_result_future")
        try:
            stream_generator = process_request(request["request"], request["body"], endpoint_url,
                                                request["request_id"], request["endpoint"], 
                                                request["background_tasks"], self.conditions[endpoint_url])
            headers, status_code = await anext(stream_generator)
            headers_dict = dict(headers)
            headers_dict["X-Request-Id"] = request["request_id"]

            response = StreamingResponse(
                stream_generator,
                status_code=status_code,
                headers=headers_dict,
                media_type="text/event-stream"
            )

            # If this request came from the queue, fulfill the future

            if result_future and not result_future.done():
                result_future.set_result(response)

        except Exception as e:
            if result_future and not result_future.done():
                result_future.set_exception(e)
            else:
                print(f"[Queue Dispatch Error] {e}")

        return
    async def _reroute_or_dispatch_stale_request(self, request: dict, original_endpoint: str):
        request_id = request.get("request_id")
        session_id = request.get("session_id")
        model = request.get("model_name")

        # TODO: Use KV cache hit estimation in future, session aware id

        if True: #replace with conditionals, move to different ep
            priority = max(0, self.calculate_request_priority(request) - 1) #priority is boosted
            new_endpoint = self.find_new_endpoint(exclude=original_endpoint)
            if new_endpoint and new_endpoint != original_endpoint:
                print(f"[Rerouting] Request {request_id} → {new_endpoint} (was {original_endpoint})")

                if self._endpoint_is_free(new_endpoint):
                    asyncio.create_task(self._dispatch_and_signal(new_endpoint, request))
                else:
                    self.enqueue(new_endpoint, request, priority)
                return

        # keep on original endpoint
        print(f"[Requeue] Request {request_id} stays at {original_endpoint}")
        queue = self.endpoint_queues[original_endpoint]
        async with self.conditions[original_endpoint]:
            self.enqueue(original_endpoint, request, priority)


    def find_new_endpoint(self, exclude: str) -> str: #TODO: get currently used router and pass in list of endpoints
        #excluding orig endpoint to preserve routing strategy
        endpoints = [ep for ep in self.endpoint_queues.keys() if ep!=exclude]

        if not endpoints:
            return exclude

        with self._lock:
            chosen = sorted(endpoints, key=lambda e:e)[self.req % len(endpoints)]
            self.req_id += 1
        return chosen
        

    def calculate_request_priority(self, request) -> int: #TODO
        return 0
    

    async def close(self):
        print("Shutting down scheduler...")

        self._shutdown_event.set()

        for task in self.endpoint_tasks.values():
            task.cancel()

        # wait for all tasks to cancel
        await asyncio.gather(*self.endpoint_tasks.values(), return_exceptions=True)

        print("Scheduler shutdown complete.")



def initialize_queue_manager(max_queue_wait_time=10, max_running_requests = 10, max_gpu_perc = 95,
                             scraper=None):
    global _global_queue_manager
    _global_queue_manager = EndpointQueueManager(max_queue_wait_time=max_queue_wait_time,
                                                 max_running_requests=max_running_requests,
                                                 max_gpu_perc=max_gpu_perc,
                                                 scraper=scraper)

def get_queue_manager() -> "EndpointQueueManager":
    if _global_queue_manager is None:
        raise ValueError("Queue manager not initialized")
    return _global_queue_manager
