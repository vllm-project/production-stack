import math
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from vllm_router.routers.routing_logic import LoadBalancedKvawareRouter


class EndpointInfo:
    def __init__(self, url: str, model_names: List[str] = None):
        self.url = url
        self.model_names = model_names or ["test-model"]


class EngineStats:
    def __init__(self, num_running_requests: int = 0, num_queuing_requests: int = 0):
        self.num_running_requests = num_running_requests
        self.num_queuing_requests = num_queuing_requests


class RequestStats:
    def __init__(self, qps: float = 0.0):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str] = None):
        self.headers = headers or {}


def _make_router(imbalanced_threshold: float = 5.0) -> LoadBalancedKvawareRouter:
    """Create a LoadBalancedKvawareRouter without starting the KV manager."""
    router = object.__new__(LoadBalancedKvawareRouter)
    router.imbalanced_threshold = imbalanced_threshold
    router.lmcache_controller_port = 9000
    router.kv_manager = MagicMock()
    router.req_id = 0
    router.instance_id_to_ip = {}
    router.session_key = None
    router.tokenizer = None
    router.threshold = 2000
    router.hash_ring = MagicMock()
    return router


def test_get_queue_length_returns_sum():
    stats = {"url1": EngineStats(num_running_requests=3, num_queuing_requests=7)}
    assert LoadBalancedKvawareRouter._get_queue_length(stats, "url1") == 10


def test_get_queue_length_missing_url_returns_zero():
    assert LoadBalancedKvawareRouter._get_queue_length({}, "url1") == 0


def test_get_queue_length_zero_stats():
    stats = {"url1": EngineStats()}
    assert LoadBalancedKvawareRouter._get_queue_length(stats, "url1") == 0


def test_is_load_balanced_when_all_equal():
    router = _make_router(imbalanced_threshold=5.0)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=10),
        "b": EngineStats(num_running_requests=10),
    }
    assert router._is_load_balanced(endpoints, engine_stats) is True


def test_is_load_balanced_diff_below_threshold():
    router = _make_router(imbalanced_threshold=5.0)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=10),
        "b": EngineStats(num_running_requests=12, num_queuing_requests=2),
    }
    # diff = 14 - 10 = 4 < 5
    assert router._is_load_balanced(endpoints, engine_stats) is True


def test_is_load_balanced_diff_equals_threshold():
    router = _make_router(imbalanced_threshold=5.0)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=10),
        "b": EngineStats(num_running_requests=15),
    }
    # diff = 5, NOT < 5 → imbalanced
    assert router._is_load_balanced(endpoints, engine_stats) is False


def test_is_load_balanced_diff_above_threshold():
    router = _make_router(imbalanced_threshold=5.0)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=1),
        "b": EngineStats(num_running_requests=20),
    }
    assert router._is_load_balanced(endpoints, engine_stats) is False


def test_is_load_balanced_infinite_threshold():
    router = _make_router(imbalanced_threshold=math.inf)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=0),
        "b": EngineStats(num_running_requests=999, num_queuing_requests=999),
    }
    assert router._is_load_balanced(endpoints, engine_stats) is True


def test_is_load_balanced_empty_endpoints():
    router = _make_router(imbalanced_threshold=5.0)
    assert router._is_load_balanced([], {}) is True


def test_is_load_balanced_single_endpoint_threshold_zero():
    router = _make_router(imbalanced_threshold=0.0)
    endpoints = [EndpointInfo(url="a")]
    engine_stats = {"a": EngineStats(num_running_requests=100)}
    # diff = 0, 0 < 0 is False → imbalanced
    assert router._is_load_balanced(endpoints, engine_stats) is False


def test_is_load_balanced_single_endpoint_positive_threshold():
    router = _make_router(imbalanced_threshold=1.0)
    endpoints = [EndpointInfo(url="a")]
    engine_stats = {"a": EngineStats(num_running_requests=100)}
    # diff = 0 < 1 → balanced
    assert router._is_load_balanced(endpoints, engine_stats) is True


def test_is_load_balanced_three_endpoints_imbalanced():
    router = _make_router(imbalanced_threshold=10.0)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b"), EndpointInfo(url="c")]
    engine_stats = {
        "a": EngineStats(num_running_requests=5),
        "b": EngineStats(num_running_requests=10),
        "c": EngineStats(num_running_requests=20),
    }
    # diff = 20 - 5 = 15 ≥ 10 → imbalanced
    assert router._is_load_balanced(endpoints, engine_stats) is False


def test_is_load_balanced_missing_stats_treated_as_zero():
    router = _make_router(imbalanced_threshold=5.0)
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=10),
        # "b" not in engine_stats → queue length = 0
    }
    # diff = 10 - 0 = 10 ≥ 5 → imbalanced
    assert router._is_load_balanced(endpoints, engine_stats) is False


def test_route_to_least_loaded_picks_shortest_queue():
    router = _make_router()
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b"), EndpointInfo(url="c")]
    engine_stats = {
        "a": EngineStats(num_running_requests=10, num_queuing_requests=5),
        "b": EngineStats(num_running_requests=2, num_queuing_requests=1),
        "c": EngineStats(num_running_requests=5, num_queuing_requests=3),
    }
    assert router._route_to_least_loaded(endpoints, engine_stats) == "b"


def test_route_to_least_loaded_picks_first_on_tie():
    router = _make_router()
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=5),
        "b": EngineStats(num_running_requests=5),
    }
    assert router._route_to_least_loaded(endpoints, engine_stats) == "a"


def test_route_to_least_loaded_missing_stats_treated_as_zero():
    router = _make_router()
    endpoints = [EndpointInfo(url="a"), EndpointInfo(url="b")]
    engine_stats = {
        "a": EngineStats(num_running_requests=5),
        # "b" missing → queue length 0
    }
    assert router._route_to_least_loaded(endpoints, engine_stats) == "b"


@pytest.mark.asyncio
async def test_route_request_imbalanced_routes_to_least_loaded():
    router = _make_router(imbalanced_threshold=5.0)
    endpoints = [EndpointInfo(url="http://a:8000"), EndpointInfo(url="http://b:8000")]
    engine_stats = {
        "http://a:8000": EngineStats(num_running_requests=1),
        "http://b:8000": EngineStats(num_running_requests=20, num_queuing_requests=5),
    }
    request = Request()
    url = await router.route_request(
        endpoints, engine_stats, {}, request, {"prompt": "hello"}
    )
    assert url == "http://a:8000"


@pytest.mark.asyncio
async def test_route_request_threshold_zero_always_load_balances():
    """With threshold=0, any non-zero spread triggers load balancing."""
    router = _make_router(imbalanced_threshold=0.0)
    endpoints = [EndpointInfo(url="http://a:8000"), EndpointInfo(url="http://b:8000")]
    engine_stats = {
        "http://a:8000": EngineStats(num_running_requests=5),
        "http://b:8000": EngineStats(num_running_requests=6),
    }
    request = Request()
    url = await router.route_request(
        endpoints, engine_stats, {}, request, {"prompt": "test"}
    )
    assert url == "http://a:8000"


@pytest.mark.asyncio
async def test_route_request_imbalanced_three_endpoints():
    """Load balancing tier with three endpoints selects the least loaded."""
    router = _make_router(imbalanced_threshold=3.0)
    endpoints = [
        EndpointInfo(url="http://a:8000"),
        EndpointInfo(url="http://b:8000"),
        EndpointInfo(url="http://c:8000"),
    ]
    engine_stats = {
        "http://a:8000": EngineStats(num_running_requests=10, num_queuing_requests=5),
        "http://b:8000": EngineStats(num_running_requests=2),
        "http://c:8000": EngineStats(num_running_requests=8, num_queuing_requests=3),
    }
    # max=15, min=2, diff=13 ≥ 3 → imbalanced
    request = Request()
    url = await router.route_request(
        endpoints, engine_stats, {}, request, {"prompt": "test"}
    )
    assert url == "http://b:8000"


@pytest.mark.asyncio
async def test_route_request_balanced_falls_back_to_qps():
    """When balanced (infinite threshold), falls back to QPS routing on empty KV hit."""
    import vllm_router.routers.routing_logic as rl_module

    router = _make_router(imbalanced_threshold=math.inf)
    endpoints = [
        EndpointInfo(url="http://a:8000", model_names=["test-model"]),
        EndpointInfo(url="http://b:8000", model_names=["test-model"]),
    ]
    engine_stats = {
        "http://a:8000": EngineStats(num_running_requests=10),
        "http://b:8000": EngineStats(num_running_requests=10),
    }
    request_stats = {
        "http://a:8000": RequestStats(qps=5),
        "http://b:8000": RequestStats(qps=10),
    }
    request = Request()
    request_json = {"prompt": "hello world"}

    router.tokenizer = MagicMock()
    router.tokenizer.encode.return_value = [1, 2, 3, 4, 5]

    original_lookup = getattr(rl_module, "LookupMsg", None)
    rl_module.LookupMsg = MagicMock()

    try:
        mock_result = MagicMock()
        mock_result.layout_info = {}
        router.query_manager = AsyncMock(return_value=mock_result)

        url = await router.route_request(
            endpoints, engine_stats, request_stats, request, request_json
        )
        # Empty KV layout → QPS fallback → lowest QPS is http://a:8000
        assert url == "http://a:8000"
    finally:
        if original_lookup is not None:
            rl_module.LookupMsg = original_lookup
        elif hasattr(rl_module, "LookupMsg"):
            delattr(rl_module, "LookupMsg")


@pytest.mark.asyncio
async def test_route_request_balanced_with_session_fallback():
    """When load is balanced and KV lookup returns no match, fallback to session routing."""
    import vllm_router.routers.routing_logic as rl_module

    router = _make_router(imbalanced_threshold=math.inf)
    router.session_key = "x-session-id"
    endpoints = [
        EndpointInfo(url="http://a:8000", model_names=["test-model"]),
        EndpointInfo(url="http://b:8000", model_names=["test-model"]),
    ]
    engine_stats = {
        "http://a:8000": EngineStats(num_running_requests=5),
        "http://b:8000": EngineStats(num_running_requests=5),
    }
    request = Request(headers={"x-session-id": "session-abc"})
    request_json = {"prompt": "hello"}

    router.tokenizer = MagicMock()
    router.tokenizer.encode.return_value = [1, 2, 3]

    original_lookup = getattr(rl_module, "LookupMsg", None)
    rl_module.LookupMsg = MagicMock()

    try:
        mock_result = MagicMock()
        mock_result.layout_info = {}
        router.query_manager = AsyncMock(return_value=mock_result)

        router.hash_ring = MagicMock()
        router.hash_ring.get_node.return_value = "http://b:8000"

        url = await router.route_request(
            endpoints, engine_stats, {}, request, request_json
        )
        assert url == "http://b:8000"
        router.hash_ring.get_node.assert_called_once_with("session-abc")
    finally:
        if original_lookup is not None:
            rl_module.LookupMsg = original_lookup
        elif hasattr(rl_module, "LookupMsg"):
            delattr(rl_module, "LookupMsg")
