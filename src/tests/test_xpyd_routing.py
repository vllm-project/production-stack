# Copyright 2024-2025 The vLLM Production Stack Authors.
# Tests for xPyD multi-endpoint routing and dynamic disagg_spec construction.

import pytest
from unittest.mock import MagicMock

from vllm_router.routers.routing_logic import DisaggregatedPrefillRouter
from vllm_router.utils import SingletonABCMeta
from vllm_router.services.request_service.request import _build_disagg_spec


class EndpointInfo:
    def __init__(self, url: str, model_label: str):
        self.url = url
        self.model_label = model_label


@pytest.fixture(autouse=True)
def clear_singleton():
    if DisaggregatedPrefillRouter in SingletonABCMeta._instances:
        del SingletonABCMeta._instances[DisaggregatedPrefillRouter]
    yield
    if DisaggregatedPrefillRouter in SingletonABCMeta._instances:
        del SingletonABCMeta._instances[DisaggregatedPrefillRouter]


class TestBuildDisaggSpec:
    def test_nixl_connector_returns_none(self):
        app_state = MagicMock()
        assert _build_disagg_spec(app_state, "nixl", "http://dec:8000") is None

    def test_lmcache_static_fallback(self):
        app_state = MagicMock()
        app_state.decoder_registry = {}
        app_state.disagg_spec = {"receiver_host": "dec-0.svc"}
        result = _build_disagg_spec(app_state, "lmcache", "http://dec:8000")
        assert result == app_state.disagg_spec

    def test_lmcache_dynamic_from_registry(self):
        app_state = MagicMock()
        app_state.decoder_registry = {
            "http://dec-0:8000": {"receiver_host": "dec-0.svc"},
            "http://dec-1:8000": {"receiver_host": "dec-1.svc"},
        }
        result = _build_disagg_spec(app_state, "lmcache", "http://dec-0:8000")
        assert result["receiver_host"] == "dec-0.svc"
        result = _build_disagg_spec(app_state, "lmcache", "http://dec-1:8000")
        assert result["receiver_host"] == "dec-1.svc"

    def test_lmcache_dynamic_returns_copy(self):
        spec = {"receiver_host": "dec-0.svc"}
        app_state = MagicMock()
        app_state.decoder_registry = {"http://dec-0:8000": spec}
        result = _build_disagg_spec(app_state, "lmcache", "http://dec-0:8000")
        result["req_id"] = "test"
        assert "req_id" not in spec

    def test_unknown_decoder_falls_back(self):
        app_state = MagicMock()
        app_state.decoder_registry = {"http://dec-0:8000": {"receiver_host": "d0"}}
        app_state.disagg_spec = {"receiver_host": "static"}
        result = _build_disagg_spec(app_state, "lmcache", "http://unknown:8000")
        assert result["receiver_host"] == "static"


class TestXPyDRoundRobin:
    def test_2p4d_distributes(self):
        router = DisaggregatedPrefillRouter(["prefill"], ["decode"], routing_threshold=4096)
        pf = [EndpointInfo(f"http://pf-{i}:8000", "prefill") for i in range(2)]
        dec = [EndpointInfo(f"http://dec-{i}:8000", "decode") for i in range(4)]
        for i in range(4):
            assert router._select_prefill_endpoint(pf) == f"http://pf-{i % 2}:8000"
            assert router._select_decode_endpoint(dec) == f"http://dec-{i % 4}:8000"

    def test_disagg_spec_matches_decoder(self):
        router = DisaggregatedPrefillRouter(["prefill"], ["decode"], routing_threshold=4096)
        dec = [EndpointInfo(f"http://dec-{i}:8000", "decode") for i in range(2)]
        registry = {
            "http://dec-0:8000": {"receiver_host": "dec-0.svc"},
            "http://dec-1:8000": {"receiver_host": "dec-1.svc"},
        }
        app_state = MagicMock()
        app_state.decoder_registry = registry
        for i in range(4):
            url = router._select_decode_endpoint(dec)
            spec = _build_disagg_spec(app_state, "lmcache", url)
            assert spec["receiver_host"] == f"dec-{i % 2}.svc"
