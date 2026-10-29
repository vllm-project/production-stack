import importlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import vllm_router.dynamic_config as dynamic_config
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


def _one_pass_watcher(monkeypatch, config_path, init_config):
    monkeypatch.setattr(SingletonMeta, "_instances", {})
    # One pass of the watch loop per _watch_worker() call.
    monkeypatch.setattr(
        DynamicConfigWatcher,
        "_sleep_or_break",
        lambda self: setattr(self, "running", False),
    )
    watcher = DynamicConfigWatcher(
        str(config_path), "JSON", 10, init_config, MagicMock()
    )
    watcher.watcher_thread.join()

    def check():
        watcher.running = True
        watcher._watch_worker()

    return watcher, check


def test_watcher_retries_failed_config_slowly(tmp_path, monkeypatch):
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
    create = MagicMock(wraps=service_discovery._create_service_discovery)
    monkeypatch.setattr(service_discovery, "_create_service_discovery", create)
    monkeypatch.setattr(dynamic_config, "FAILED_CONFIG_SKIP_CHECKS", 2, raising=False)
    watcher, check = _one_pass_watcher(
        monkeypatch, config_path, DynamicRouterConfig(**good)
    )

    assert create.call_count == 1  # the watcher's first check failed
    check()
    check()
    assert create.call_count == 1  # skipped twice
    check()
    assert create.call_count == 2  # retried

    config_path.write_text(json.dumps(good))
    check()
    assert create.call_count == 3
    assert service_discovery.get_service_discovery().urls == ["http://localhost:8001"]

    # Applying the failed config again is tried at once, not skipped.
    config_path.write_text(json.dumps(bad))
    check()
    assert create.call_count == 4


def test_watcher_applies_failed_config_once_callbacks_importable(tmp_path, monkeypatch):
    good = {
        "service_discovery": "static",
        "routing_logic": "roundrobin",
        "static_backends": "http://localhost:8001",
        "static_models": "m",
    }
    with_callbacks = {**good, "callbacks": "late_callbacks_module.callbacks"}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(with_callbacks))
    monkeypatch.setattr(service_discovery, "_global_service_discovery", MagicMock())
    monkeypatch.setattr(dynamic_config, "FAILED_CONFIG_SKIP_CHECKS", 1, raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))
    watcher, check = _one_pass_watcher(
        monkeypatch, config_path, DynamicRouterConfig(**good)
    )

    # The watcher's first check failed: the module isn't there yet.
    assert watcher.current_config == DynamicRouterConfig(**good)

    (tmp_path / "late_callbacks_module.py").write_text("callbacks = 'loaded'\n")
    importlib.invalidate_caches()
    check()  # skipped
    assert watcher.current_config == DynamicRouterConfig(**good)
    check()  # retried
    sys.modules.pop("late_callbacks_module", None)
    assert watcher.current_config == DynamicRouterConfig(**with_callbacks)
    assert watcher.app.state.callbacks == "loaded"
