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
        """
        Initializes the queue manager responsible for scheduling and dispatching
        requests to backend endpoints based on GPU load, request priority, and wait time.

        Args:
            max_queue_wait_time (float): Maximum time (in seconds) a request can wait before being rerouted.
            max_running_requests (int): Maximum number of concurrent requests allowed on an endpoint.
            max_gpu_perc (float): Maximum allowed GPU usage percentage per endpoint.
            scraper: Optional engine stats scraper for monitoring backend load.
        """
        self.endpoint_queues: Dict[str, asyncio.PriorityQueue] = {}
        self.conditions: Dict[str, asyncio.Condition] = {}

        self.scraper = scraper or get_engine_stats_scraper()
        if self.scraper is None:
            raise RuntimeError("Engine stats scraper not initialized.")
        
        # User configurable fields
        self.max_running_requests = max_running_requests
        self.max_gpu_perc = max_gpu_perc
        self.max_queue_wait_time = max_queue_wait_time

        # Stale request round-robin fallback strategy
        self.req_id = 0
        self._lock = Lock()

        # Kept for shutdown
        self.endpoint_tasks: Dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

    async def register_endpoint(self, endpoint_url: str):
        """
        Registers an endpoint with the queue manager. Initializes a queue and
        a scheduler loop for the endpoint if not already registered.

        Args:
            endpoint_url (str): The unique identifier (typically URL) for the backend endpoint.
        """
        if endpoint_url in self.endpoint_queues:
            return # Already registered
        
        self.endpoint_queues[endpoint_url] = asyncio.PriorityQueue()
        self.conditions[endpoint_url] = asyncio.Condition()
        task = asyncio.create_task(self._scheduler_loop(endpoint_url))
        self.endpoint_tasks[endpoint_url] = task

    async def enqueue(
        self, endpoint_url: str, request: Dict[str, Any], 
        priority: int = 0
    ):
        """
        Adds a request to the endpoint-specific priority queue and notifies
        the scheduler that a new request is available.

        Args:
            endpoint_url (str): The endpoint to which the request should be enqueued.
            request (dict): Metadata and payload for the request.
            priority (int): Priority value (lower values are dequeued earlier).
        """
        if self._shutdown_event.is_set():
            raise RuntimeError("Scheduler is shutting down, can't enqueue new requests.")


        await self.endpoint_queues[endpoint_url].put((priority, time.time(), request))
        async with self.conditions[endpoint_url]:
            self.conditions[endpoint_url].notify() # Tell queue that a request is available

    async def _scheduler_loop(self, endpoint_url: str):
        """
        Continuously monitors the request queue for the given endpoint, and
        dispatches or reroutes requests based on endpoint load and wait time.

        This function runs in the background per endpoint.
        """

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
                    continue  # Queue is empty

                if self._endpoint_is_free(endpoint_url):
                    try:
                        _, _, request = queue.get_nowait() #Dequeue
                        asyncio.create_task(self._dispatch_and_signal(endpoint_url, request))
                    except Exception as e:
                        print(f"[Dispatch error] {e}")
                    continue
            
                wait_duration = time.time() - enqueue_time
                #print(f"Request waited {wait_duration:.2f}s, threshold is {self.max_queue_wait_time}s")
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


    def _endpoint_is_free(self, endpoint_url: str) -> bool: #TODO: What stats could be relevant
        """
        Determines whether the specified endpoint is currently available to handle a new request,
        based on configured load and GPU thresholds.

        Args:
            endpoint_url (str): The endpoint to check.

        Returns:
            bool: True if the endpoint is under capacity, False otherwise.
        """

        stats = self.scraper.get_engine_stats().get(endpoint_url)
        return (stats 
                and stats.num_running_requests < self.max_running_requests 
                and stats.gpu_cache_usage_perc < self.max_gpu_perc)

    async def _dispatch_and_signal(self, endpoint_url: str, request: Dict[str, Any]):
        """
        Sends a request to the target endpoint and fulfills any associated future
        used by upstream logic to await response.

        Args:
            endpoint_url (str): The backend endpoint to dispatch the request to.
            request (dict): Request metadata, including content and completion future.
        """
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

            # Fulfill the future
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
        """
        Handles requests that have waited in the queue too long. Either reroutes
        them to a different eligible endpoint or re-enqueues them with higher priority.

        Args:
            request (dict): The request object to be rerouted or re-enqueued.
            original_endpoint (str): The endpoint where the request was originally queued.
        """

        # TODO: Use KV cache hit estimation in future, session aware id

        if True: # Replace with conditionals, ie, no session affinity or high KV cache matches
            priority = max(0, self.calculate_request_priority(request) - 1) #priority is boosted
            new_endpoint = self.find_new_endpoint(exclude=original_endpoint)
            if new_endpoint and new_endpoint != original_endpoint:
                #print(f"[Rerouting] Request {request_id} → {new_endpoint} (was {original_endpoint})")

                if self._endpoint_is_free(new_endpoint):
                    asyncio.create_task(self._dispatch_and_signal(new_endpoint, request))
                else:
                    self.enqueue(new_endpoint, request, priority)
                return

        # Keep original endpoint
        #print(f"[Requeue] Request {request_id} stays at {original_endpoint}")
        queue = self.endpoint_queues[original_endpoint]
        async with self.conditions[original_endpoint]:
            self.enqueue(original_endpoint, request, priority)


    def find_new_endpoint(self, exclude: str) -> str: 
        """
        Selects a new endpoint to reroute a stale request, excluding the original one.
        Uses round-robin logic to rotate among available endpoints.

        Args:
            exclude (str): The endpoint to avoid in selection.

        Returns:
            str: Chosen new endpoint (or original if no other available).
        """
        #TODO: Get currently used router and pass in list of endpoints excluding orig endpoint to preserve routing strategy
        endpoints = [ep for ep in self.endpoint_queues.keys() if ep!=exclude]

        if not endpoints:
            return exclude

        with self._lock:
            chosen = sorted(endpoints, key=lambda e:e)[self.req % len(endpoints)]
            self.req_id += 1
        return chosen
        

    def calculate_request_priority(self, request) -> int: #TODO
        """
        Determines the priority of a request. Placeholder for future QoS heuristics.

        Args:
            request (dict): The request to score.

        Returns:
            int: Priority value (lower = higher priority).
        """
        return 0
    

    async def close(self):
        """
        Shuts down the queue manager by cancelling all scheduler tasks
        and waiting for them to complete. Ensures no new requests are accepted.
        """

        self._shutdown_event.set()

        for task in self.endpoint_tasks.values():
            task.cancel()

        # wait for all tasks to cancel
        await asyncio.gather(*self.endpoint_tasks.values(), return_exceptions=True)

        print("Scheduler shutdown complete.")



def initialize_queue_manager(max_queue_wait_time=10, max_running_requests = 10, max_gpu_perc = 95,
                             scraper=None):
    """
    Initializes and globally registers the queue manager with the specified configuration.

    Args:
        max_queue_wait_time (float): Max time a request can wait in queue before reroute.
        max_running_requests (int): Max concurrent requests per endpoint.
        max_gpu_perc (float): Max allowed GPU usage per endpoint.
        scraper: Optional engine stats scraper override.
    """

    global _global_queue_manager
    _global_queue_manager = EndpointQueueManager(max_queue_wait_time=max_queue_wait_time,
                                                 max_running_requests=max_running_requests,
                                                 max_gpu_perc=max_gpu_perc,
                                                 scraper=scraper)

def get_queue_manager() -> "EndpointQueueManager":
    """
    Returns the globally initialized queue manager instance.

    Raises:
        ValueError: If the queue manager has not been initialized.

    Returns:
        EndpointQueueManager: The singleton instance of the queue manager.
    """
    
    if _global_queue_manager is None:
        raise ValueError("Queue manager not initialized")
    return _global_queue_manager
