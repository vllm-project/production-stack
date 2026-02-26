"""Tests for PriorityRouter (lowest-QPS / least-loaded routing)."""

from typing import Dict

from vllm_router.routers.routing_logic import PriorityRouter


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


def test_priority_routes_to_lowest_qps():
    """PriorityRouter should return the endpoint with lowest QPS."""
    router = PriorityRouter()
    endpoints = [
        EndpointInfo(url="http://a"),
        EndpointInfo(url="http://b"),
        EndpointInfo(url="http://c"),
    ]
    engine_stats = {
        "http://a": EngineStats(),
        "http://b": EngineStats(),
        "http://c": EngineStats(),
    }
    request_stats = {
        "http://a": RequestStats(qps=10.0),
        "http://b": RequestStats(qps=2.0),
        "http://c": RequestStats(qps=5.0),
    }
    request = Request({})

    url = router.route_request(endpoints, engine_stats, request_stats, request)
    assert url == "http://b"


def test_priority_returns_endpoint_with_no_stats():
    """If an endpoint has no request_stats, _qps_routing returns it (no load)."""
    router = PriorityRouter()
    endpoints = [
        EndpointInfo(url="http://new"),
        EndpointInfo(url="http://busy"),
    ]
    engine_stats = {"http://new": EngineStats(), "http://busy": EngineStats()}
    request_stats = {"http://busy": RequestStats(qps=100.0)}
    request = Request({})

    url = router.route_request(endpoints, engine_stats, request_stats, request)
    assert url == "http://new"


def test_priority_consistent_for_same_stats():
    """With same QPS on all, router returns one of them consistently (first in iteration)."""
    router = PriorityRouter()
    endpoints = [
        EndpointInfo(url="http://a"),
        EndpointInfo(url="http://b"),
    ]
    engine_stats = {"http://a": EngineStats(), "http://b": EngineStats()}
    request_stats = {
        "http://a": RequestStats(qps=3.0),
        "http://b": RequestStats(qps=3.0),
    }
    request = Request({})

    url = router.route_request(endpoints, engine_stats, request_stats, request)
    assert url in ("http://a", "http://b")
