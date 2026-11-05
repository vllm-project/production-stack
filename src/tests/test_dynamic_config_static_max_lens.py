import tempfile
from unittest.mock import MagicMock

import yaml

from vllm_router import dynamic_config
from vllm_router.dynamic_config import DynamicConfigWatcher, DynamicRouterConfig


def test_from_yaml_carries_max_model_len_into_reconfigured_static_discovery(
    monkeypatch,
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".yaml") as f:
        f.write(
            yaml.safe_dump(
                {
                    "service_discovery": "static",
                    "routing_logic": "roundrobin",
                    "static_models": {
                        "llama3": {
                            "static_backends": ["http://a:8000"],
                            "max_model_len": 131072,
                        },
                        "qwen": {"static_backends": ["http://b:8000"]},
                    },
                }
            ).encode()
        )
        f.flush()
        config = DynamicRouterConfig.from_yaml(f.name)

    assert config.static_model_max_lens == "llama3:131072"

    reconfigure = MagicMock()
    monkeypatch.setattr(dynamic_config, "reconfigure_service_discovery", reconfigure)
    DynamicConfigWatcher.reconfigure_service_discovery(MagicMock(), config)

    assert reconfigure.call_args.kwargs["model_max_lens"] == {"llama3": 131072}
