from typing import Dict, List
from unittest.mock import Mock

import pytest

from vllm_router.routers.routing_logic import TimeTrackingRouter
from vllm_router.service_discovery import EndpointInfo, EndpointStats
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats


# Mock definitions
class EndpointStats:
    def __init__(self):
        self.times = []

    def add_completion_time(self, duration: float):
        self.times.append(duration)

    def mean(self):
        return sum(self.times) / len(self.times) if self.times else 0.0

    def stdev(self):
        if len(self.times) < 2:
            return 0.0
        mean = self.mean()
        return (sum((x - mean) ** 2 for x in self.times) / (len(self.times) - 1)) ** 0.5


class EndpointInfo:
    def __init__(self, url: str, current_load: int = 0):
        self.url = url
        self.current_load = current_load
        self.mean_completion_time = None
        self.std_completion_time = None


class Request:
    pass  # can be expanded as needed


# Import the router class here if defined externally
# from my_router_module import TimeTrackingRouter


@pytest.mark.asyncio
async def test_time_tracking_router_prefers_fastest_endpoint():
    router = TimeTrackingRouter(alpha=1.0, beta=1.0, gamma=1.0)

    endpoint_a = EndpointInfo("http://endpoint-a", current_load=2)
    endpoint_b = EndpointInfo("http://endpoint-b", current_load=1)

    router.register_endpoint(endpoint_a)
    router.register_endpoint(endpoint_b)

    # Simulate completion history
    router.record_completion(endpoint_a, 2.0)  # mean = 2.0
    router.record_completion(endpoint_a, 2.5)
    router.record_completion(endpoint_b, 1.0)  # mean = 1.0
    router.record_completion(endpoint_b, 1.2)

    endpoints = [endpoint_a, endpoint_b]
    engine_stats: Dict[str, any] = {}
    request_stats: Dict[str, any] = {}
    request = Request()
    request_json = {}

    selected = await router.route_request(
        endpoints, engine_stats, request_stats, request, request_json
    )

    assert (
        selected == "http://endpoint-b"
    ), "Router should prefer the faster and less loaded endpoint"
