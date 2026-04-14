import random
from collections import Counter
from typing import Dict, List, Tuple

import pytest

from vllm_router.routers.routing_logic import RoundRobinRouter, cleanup_routing_logic


@pytest.fixture(autouse=True)
def cleanup_router():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


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
        pass


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


def assert_even_distribution(route_counts: Counter):
    counts = route_counts.values()
    assert max(counts) - min(counts) <= 1


def test_roundrobin_logic(
    dynamic_discoveries: int = 10, max_endpoints: int = 1000, max_requests: int = 10000
):
    """
    Ensure that all active urls have roughly same number of requests (difference at most 1)
    """
    router = RoundRobinRouter()

    def assert_router_stays_balanced(num_endpoints: int, num_requests: int):
        endpoints, engine_stats, request_stats = generate_request_args(num_endpoints)
        route_counts = Counter()
        for _ in range(num_requests):
            request = generate_request()
            url = router.route_request(endpoints, engine_stats, request_stats, request)
            route_counts[url] += 1

        assert_even_distribution(route_counts)

    for _ in range(dynamic_discoveries):
        num_endpoints = random.randint(1, max_endpoints)
        num_requests = random.randint(1, max_requests)
        assert_router_stays_balanced(num_endpoints, num_requests)


def test_roundrobin_keeps_state_per_endpoint_set():
    router = RoundRobinRouter()
    request = generate_request()
    engine_stats = {}
    request_stats = {}
    endpoints_a = [EndpointInfo(url="a0"), EndpointInfo(url="a1")]
    endpoints_b = [EndpointInfo(url="b0"), EndpointInfo(url="b1")]
    route_counts_a = Counter()
    route_counts_b = Counter()

    for _ in range(100):
        url_a = router.route_request(endpoints_a, engine_stats, request_stats, request)
        route_counts_a[url_a] += 1
        url_b = router.route_request(endpoints_b, engine_stats, request_stats, request)
        route_counts_b[url_b] += 1

    assert_even_distribution(route_counts_a)
    assert_even_distribution(route_counts_b)


def test_roundrobin_keeps_state_when_endpoint_order_changes():
    router = RoundRobinRouter()
    request = generate_request()
    engine_stats = {}
    request_stats = {}
    endpoints_a = [EndpointInfo(url="a0"), EndpointInfo(url="a1")]
    endpoints_a_reordered = [EndpointInfo(url="a1"), EndpointInfo(url="a0")]

    assert (
        router.route_request(endpoints_a, engine_stats, request_stats, request) == "a0"
    )
    assert (
        router.route_request(
            endpoints_a_reordered,
            engine_stats,
            request_stats,
            request,
        )
        == "a1"
    )


def test_roundrobin_rejects_empty_endpoint_list():
    router = RoundRobinRouter()

    with pytest.raises(ValueError, match="at least one endpoint"):
        router.route_request([], {}, {}, generate_request())
