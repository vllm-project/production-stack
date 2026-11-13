from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillRouter,
    cleanup_routing_logic,
)


@pytest.fixture(autouse=True)
def cleanup_router():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


def endpoint(url, label):
    return SimpleNamespace(url=url, model_label=label)


def test_missing_prefill_endpoints_returns_503():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [endpoint("http://d:8000", "decode")]
    with pytest.raises(HTTPException) as exc:
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 1})
    assert exc.value.status_code == 503
    assert "PREFILL_SERVICE_UNAVAILABLE" in exc.value.detail


def test_missing_decode_endpoints_returns_503():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [endpoint("http://p:8000", "prefill")]
    with pytest.raises(HTTPException) as exc:
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 16})
    assert exc.value.status_code == 503
    assert "DECODE_SERVICE_UNAVAILABLE" in exc.value.detail


def test_routes_normally_when_both_present():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        endpoint("http://p:8000", "prefill"),
        endpoint("http://d:8000", "decode"),
    ]
    assert (
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 1})
        == "http://p:8000"
    )
    assert (
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 8})
        == "http://d:8000"
    )
