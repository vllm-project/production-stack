import random
from typing import Dict, List, Tuple

from vllm_router.routers.routing_logic import RoundRobinRouter


class EndpointInfo:
    def __init__(self, url: str):
        self.url = url


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


class EngineStats:
    def __init__(self):
        return


def generate_request_args(
    num_endpoints: int, qps_range: int = 0
) -> Tuple[List[EndpointInfo], Dict[str, EngineStats], Dict[str, RequestStats]]:
    endpoints = [
        EndpointInfo(
            url=f"{endpoint_index}",
        )
        for endpoint_index in range(num_endpoints)
    ]
    engine_stats = {
        f"{endpoint_index}": EngineStats() for endpoint_index in range(num_endpoints)
    }
    request_stats = {
        f"{endpoint_index}": RequestStats(qps=random.uniform(0, qps_range))
        for endpoint_index in range(num_endpoints)
    }
    return endpoints, engine_stats, request_stats


def generate_request(request_type="http") -> Request:
    return Request({"type": request_type})


def test_roundrobin_logic(
    dynamic_discoveries: int = 10, max_endpoints: int = 1000, max_requests: int = 10000
):
    """
    Ensure that all active urls have roughly same number of requests (difference at most 1)
    """
    router = RoundRobinRouter()

    def _fixed_router_check(num_endpoints: int, num_requests: int) -> bool:
        # Make num_requests requests to the router and check even output distribution
        endpoints, engine_stats, request_stats = generate_request_args(num_endpoints)
        output_distribution = {}
        for request_idx in range(num_requests):
            request = generate_request()
            url = router.route_request(endpoints, engine_stats, request_stats, request)
            output_distribution[url] = output_distribution.get(url, 0) + 1
        request_counts = output_distribution.values()
        return max(request_counts) - min(request_counts) <= 1

    for _ in range(dynamic_discoveries):
        num_endpoints = random.randint(1, max_endpoints)
        num_requests = random.randint(1, max_requests)
        # Perform router check
        res = _fixed_router_check(num_endpoints, num_requests)
        assert res
