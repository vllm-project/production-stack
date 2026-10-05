from types import SimpleNamespace

import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    DisaggregatedPrefillRouter,
    _parse_model_labels,
    cleanup_routing_logic,
)


@pytest.fixture(autouse=True)
def cleanup_router():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


def endpoint(url, label):
    return SimpleNamespace(url=url, model_label=label)


def test_parse_model_labels():
    assert _parse_model_labels("a, b,,c ") == ["a", "b", "c"]
    assert _parse_model_labels(["a", "b"]) == ["a", "b"]
    assert _parse_model_labels(None) == []
    assert _parse_model_labels("") == []


def test_orchestrated_labels_match_exactly():
    # The CLI passes the raw flag strings; a pod label that is only a substring
    # of the flag value must not be treated as a prefill/decode pod.
    router = DisaggregatedPrefillOrchestratedRouter("glm-prefill-short", "glm-decode")
    prefill, decode = router._find_endpoints(
        [
            endpoint("http://p-short:8000", "glm-prefill-short"),
            endpoint("http://p:8000", "glm-prefill"),
            endpoint("http://d:8000", "glm-decode"),
            endpoint("http://x:8000", "glm"),
        ]
    )
    assert [e.url for e in prefill] == ["http://p-short:8000"]
    assert [e.url for e in decode] == ["http://d:8000"]


def test_orchestrated_comma_separated_labels():
    router = DisaggregatedPrefillOrchestratedRouter("p1,p2", "d1")
    prefill, decode = router._find_endpoints(
        [
            endpoint("http://p1:8000", "p1"),
            endpoint("http://p2:8000", "p2"),
            endpoint("http://d1:8000", "d1"),
        ]
    )
    assert sorted(e.url for e in prefill) == ["http://p1:8000", "http://p2:8000"]
    assert [e.url for e in decode] == ["http://d1:8000"]


def test_disaggregated_prefill_router_labels_match_exactly():
    router = DisaggregatedPrefillRouter("prefill-short", "decode")
    endpoints = [
        endpoint("http://p:8000", "prefill"),
        endpoint("http://p-short:8000", "prefill-short"),
        endpoint("http://d:8000", "decode"),
    ]
    assert router.route_request(endpoints, {}, {}, None, {"max_tokens": 1}) == "http://p-short:8000"
    assert router.route_request(endpoints, {}, {}, None, {"max_tokens": 64}) == "http://d:8000"
