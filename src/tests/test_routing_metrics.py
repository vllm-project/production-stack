import importlib.util
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    KvawareRouter,
    RoundRobinRouter,
    SessionRouter,
    cleanup_routing_logic,
)
from vllm_router.services.metrics_service import routing_decisions_total

_LMCACHE_AVAILABLE = importlib.util.find_spec("lmcache") is not None
requires_lmcache = pytest.mark.skipif(
    not _LMCACHE_AVAILABLE, reason="lmcache not installed"
)


class EndpointInfo:
    def __init__(
        self,
        url: str,
        model_label: str = "",
        model_names: List[str] | None = None,
    ):
        self.url = url
        self.model_label = model_label
        self.model_names = model_names or ["test-model"]


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class Request:
    def __init__(self, headers: Dict[str, str], body: Dict[str, Any] = None):
        self.headers = headers
        self.body = body


@pytest.fixture(autouse=True)
def _cleanup_router_singletons():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


def _counter_value(server: str, model: str, algorithm: str, outcome: str) -> float:
    """Return the current value of the routing decisions counter for the given labels."""
    for metric in routing_decisions_total.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            labels = sample.labels
            if (
                labels.get("server") == server
                and labels.get("model") == model
                and labels.get("algorithm") == algorithm
                and labels.get("outcome") == outcome
            ):
                return sample.value
    return 0.0


def test_roundrobin_records_success_outcome_with_model():
    router = RoundRobinRouter()
    endpoints = [EndpointInfo(url="http://engine1.com", model_names=["llama-3"])]
    request = Request(headers={})

    before = _counter_value("http://engine1.com", "llama-3", "roundrobin", "success")
    router.route_request(endpoints, {}, {}, request)
    after = _counter_value("http://engine1.com", "llama-3", "roundrobin", "success")

    assert after - before == 1


@pytest.mark.asyncio
async def test_session_router_records_fallback_when_no_session_id():
    router = SessionRouter(session_key="session_id")
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={})
    request_json = {"model": "llama-3"}

    before = _counter_value("http://engine2.com", "llama-3", "session", "fallback")
    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )
    after = _counter_value("http://engine2.com", "llama-3", "session", "fallback")

    assert url == "http://engine2.com"
    assert after - before == 1


@pytest.mark.asyncio
async def test_session_router_records_success_with_session_id():
    router = SessionRouter(session_key="session_id")
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={"session_id": "abc123"})
    request_json = {"model": "llama-3"}

    before = {
        ep.url: _counter_value(ep.url, "llama-3", "session", "success")
        for ep in endpoints
    }
    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )
    after = _counter_value(url, "llama-3", "session", "success")

    assert after - before[url] == 1


@requires_lmcache
@pytest.mark.asyncio
async def test_kvaware_router_records_success_for_session_hashring_on_kv_miss():
    # __new__ + manual field setup bypasses the lmcache controller in __init__.
    router = KvawareRouter.__new__(KvawareRouter)
    router._initialized = True
    router.session_key = "session_id"
    router.threshold = 2000
    router.tokenizer = MagicMock()
    router.tokenizer.encode = MagicMock(return_value=[1, 2, 3])
    router.instance_id_to_ip = {}
    from uhashring import HashRing

    router.hash_ring = HashRing()
    empty_layout = MagicMock()
    empty_layout.layout_info = {}
    router.query_manager = AsyncMock(return_value=empty_layout)

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={"session_id": "abc123"})
    request_json = {"model": "llama-3", "prompt": "hi"}

    before = {
        ep.url: _counter_value(ep.url, "llama-3", "kvaware", "success")
        for ep in endpoints
    }
    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )
    after = _counter_value(url, "llama-3", "kvaware", "success")

    assert after - before[url] == 1


def test_disaggregated_prefill_orchestrated_records_two_decisions_per_request():
    router = DisaggregatedPrefillOrchestratedRouter(
        prefill_model_labels=["prefill"],
        decode_model_labels=["decode"],
    )
    prefill_endpoints = [EndpointInfo(url="http://prefill1.com", model_label="prefill")]
    decode_endpoints = [EndpointInfo(url="http://decode1.com", model_label="decode")]

    before_prefill = _counter_value(
        "http://prefill1.com",
        "llama-3",
        "disaggregated_prefill_orchestrated",
        "success",
    )
    before_decode = _counter_value(
        "http://decode1.com",
        "llama-3",
        "disaggregated_prefill_orchestrated",
        "success",
    )

    router.select_prefill_endpoint(prefill_endpoints, "llama-3")
    router.select_decode_endpoint(decode_endpoints, "llama-3")

    after_prefill = _counter_value(
        "http://prefill1.com",
        "llama-3",
        "disaggregated_prefill_orchestrated",
        "success",
    )
    after_decode = _counter_value(
        "http://decode1.com",
        "llama-3",
        "disaggregated_prefill_orchestrated",
        "success",
    )

    assert after_prefill - before_prefill == 1
    assert after_decode - before_decode == 1


def test_record_decision_handles_missing_model_label():
    router = RoundRobinRouter()
    router._record_decision(server_url="", model="")
    value = _counter_value("unknown", "unknown", "roundrobin", "success")
    assert value >= 1
