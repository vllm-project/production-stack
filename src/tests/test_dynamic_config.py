import json
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


def test_config_file_may_set_startup_only_flags(tmp_path):
    """Flags such as log_stats are read from the file at startup; the watcher
    must ignore them on reload instead of failing with TypeError."""
    path = tmp_path / "router.yaml"
    path.write_text(
        "service_discovery: static\n"
        "routing_logic: roundrobin\n"
        "static_models:\n"
        "  test-model:\n"
        "    static_backends:\n"
        "    - http://engine:8000\n"
        "log_stats: true\n"
        "engine_stats_interval: 15\n"
    )
    config = DynamicRouterConfig.from_yaml(str(path))
    assert config.routing_logic == "roundrobin"
    assert config.static_backends == "http://engine:8000"
    assert config.static_models == "test-model"


def test_config_file_rejects_unknown_keys(tmp_path):
    """A typo must not silently reset the field it meant to set."""
    path = tmp_path / "router.json"
    path.write_text(
        json.dumps(
            {
                "service_discovery": "static",
                "routing_logic": "roundrobin",
                "callback": "my_module.my_callbacks",
            }
        )
    )
    with pytest.raises(ValueError, match="callback"):
        DynamicRouterConfig.from_json(str(path))
