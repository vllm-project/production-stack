from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vllm_router.dynamic_config import DynamicConfigWatcher, DynamicRouterConfig
from vllm_router.routers.routing_logic import cleanup_routing_logic


@pytest.fixture(autouse=True)
def clean_router_singletons():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


@pytest.mark.parametrize(
    "routing_logic",
    ["disaggregated_prefill", "disaggregated_prefill_orchestrated"],
)
def test_reconfigure_routing_logic_keeps_prefill_decode_labels(routing_logic):
    config = DynamicRouterConfig(
        service_discovery="static",
        routing_logic=routing_logic,
        prefill_model_labels="prefill-a,prefill-b",
        decode_model_labels="decode",
    )
    watcher = SimpleNamespace(app=MagicMock())

    DynamicConfigWatcher.reconfigure_routing_logic(watcher, config)

    router = watcher.app.state.router
    assert router.prefill_model_labels == ["prefill-a", "prefill-b"]
    assert router.decode_model_labels == ["decode"]
