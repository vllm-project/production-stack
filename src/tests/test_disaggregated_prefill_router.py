"""Unit tests for DisaggregatedPrefillRouter empty-label handling."""

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


def test_prefill_without_matching_label_raises_503():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [SimpleNamespace(url="http://d:8000", model_label="decode")]

    with pytest.raises(HTTPException) as exc:
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 1})

    assert exc.value.status_code == 503
    assert "PREFILL_SERVICE_UNAVAILABLE" in exc.value.detail


def test_decode_without_matching_label_raises_503():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [SimpleNamespace(url="http://p:8000", model_label="prefill")]

    with pytest.raises(HTTPException) as exc:
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 16})

    assert exc.value.status_code == 503
    assert "DECODE_SERVICE_UNAVAILABLE" in exc.value.detail


def test_empty_endpoint_list_raises_503_for_prefill_and_decode():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])

    with pytest.raises(HTTPException) as prefill_exc:
        router.route_request([], {}, {}, None, {"max_tokens": 1})
    assert prefill_exc.value.status_code == 503
    assert "PREFILL_SERVICE_UNAVAILABLE" in prefill_exc.value.detail

    with pytest.raises(HTTPException) as decode_exc:
        router.route_request([], {}, {}, None, {"max_tokens": 16})
    assert decode_exc.value.status_code == 503
    assert "DECODE_SERVICE_UNAVAILABLE" in decode_exc.value.detail


def test_matching_labels_still_select_first_endpoint():
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        SimpleNamespace(url="http://p:8000", model_label="prefill"),
        SimpleNamespace(url="http://d:8000", model_label="decode"),
    ]

    assert (
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 1})
        == "http://p:8000"
    )
    assert (
        router.route_request(endpoints, {}, {}, None, {"max_tokens": 16})
        == "http://d:8000"
    )
