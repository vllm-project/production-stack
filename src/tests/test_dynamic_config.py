import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import vllm_router.service_discovery as service_discovery
from vllm_router.dynamic_config import DynamicConfigWatcher, DynamicRouterConfig
from vllm_router.routers.routing_logic import cleanup_routing_logic
from vllm_router.utils import SingletonMeta


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


def test_watcher_reapplies_config_after_failed_reload(tmp_path, monkeypatch):
    good = {
        "service_discovery": "static",
        "routing_logic": "roundrobin",
        "static_backends": "http://localhost:8001",
        "static_models": "m",
    }
    bad = {**good, "static_backends": "http://localhost:8002", "routing_logic": "bogus"}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(bad))
    monkeypatch.setattr(service_discovery, "_global_service_discovery", MagicMock())
    monkeypatch.setattr(SingletonMeta, "_instances", {})
    # One pass of the watch loop per _watch_worker() call.
    monkeypatch.setattr(
        DynamicConfigWatcher,
        "_sleep_or_break",
        lambda self: setattr(self, "running", False),
    )

    watcher = DynamicConfigWatcher(
        str(config_path), "JSON", 10, DynamicRouterConfig(**good), MagicMock()
    )
    watcher.watcher_thread.join()
    assert service_discovery.get_service_discovery().urls == ["http://localhost:8002"]

    config_path.write_text(json.dumps(good))
    watcher.running = True
    watcher._watch_worker()
    assert service_discovery.get_service_discovery().urls == ["http://localhost:8001"]
