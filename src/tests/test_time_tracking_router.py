from typing import Dict

import pytest

from vllm_router.routers.routing_logic import TimeTrackingRouter
from vllm_router.service_discovery import EndpointInfo

# from vllm_router.stats.engine_stats import EngineStats
# from vllm_router.stats.request_stats import RequestStats


class Request:
    pass  # can be expanded as needed


# Import the router class here if defined externally
# from my_router_module import TimeTrackingRouter


@pytest.mark.asyncio
async def test_time_tracking_router_prefers_fastest_endpoint():
    router = TimeTrackingRouter(alpha=1.0, beta=0.5)

    endpoint_a = EndpointInfo(
        url="http://endpoint-a",
        model_names=[],
        Id="a",
        added_timestamp=0,
        model_label="A",
        sleep=False,
    )
    endpoint_b = EndpointInfo(
        url="http://endpoint-b",
        model_names=[],
        Id="b",
        added_timestamp=0,
        model_label="B",
        sleep=False,
    )

    router.update_endpoint(endpoint_a)
    router.update_endpoint(endpoint_b)

    # Simulate completion history
    router.record_completion(endpoint_a.url, 2.0)  # mean = 2.0
    router.record_completion(endpoint_a.url, 2.5)
    router.record_completion(endpoint_b.url, 1.0)  # mean = 1.0
    router.record_completion(endpoint_b.url, 1.2)

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
