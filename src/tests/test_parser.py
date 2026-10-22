import argparse
import json
import sys
import tempfile
from unittest.mock import MagicMock

import pytest
import yaml

from vllm_router.parsers import parser


def test_verify_required_args_provided_when_routing_logic_missing_raises_systemexit() -> (
    None
):
    args_mock = MagicMock(routing_logic=None, service_discovery="static")
    with pytest.raises(SystemExit):
        parser.verify_required_args_provided(args_mock)


def test_verify_required_args_provided_when_service_discovery_missing_raises_systemexit() -> (
    None
):
    args_mock = MagicMock(
        routing_logic="roundrobin",
        service_discovery=None,
        external_providers_config=None,
    )
    with pytest.raises(SystemExit):
        parser.verify_required_args_provided(args_mock)


def test_load_initial_config_from_config_file_if_required_when_config_files_are_not_provided_returns_args_without_changes() -> (
    None
):
    args_mock = MagicMock(
        example=True, dynamic_config_yaml=None, dynamic_config_json=None
    )
    assert (
        parser.load_initial_config_from_config_file_if_required(MagicMock(), args_mock)
        == args_mock
    )


def test_load_initial_config_from_config_file_if_required_when_yaml_config_file_is_provided_adds_values_to_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.NamedTemporaryFile() as f:
        monkeypatch.setattr(sys, "argv", [sys.argv[0], "--dynamic-config-yaml", f.name])
        f.write(
            yaml.safe_dump(
                {
                    "routing_logic": "roundrobin",
                    "service_discovery": "static",
                    "callbacks": "module.custom.callback_handler",
                    "static_models": {
                        "bge-m3": {
                            "static_backends": [
                                "https://endpoint1.example.com/bge-m3",
                                "https://endpoint2.example.com/bge-m3",
                            ],
                            "static_model_type": "embeddings",
                        },
                        "bge-reranker-v2-m3": {
                            "static_backends": [
                                "https://endpoint3.example.com/bge-reranker-v2-m3",
                            ],
                            "static_model_type": "rerank",
                        },
                    },
                    "static_aliases": {"text-embedding-3-small": "bge-m3"},
                }
            ).encode()
        )
        f.seek(0)
        test_parser = argparse.ArgumentParser("test")
        test_parser.add_argument("--dynamic-config-yaml", type=str)
        test_parser.add_argument("--dynamic-config-json", type=str)
        args = test_parser.parse_args()
        args = parser.load_initial_config_from_config_file_if_required(
            test_parser, args
        )
        assert args.routing_logic == "roundrobin"
        assert args.service_discovery == "static"
        assert args.callbacks == "module.custom.callback_handler"
        assert (
            args.static_backends
            == "https://endpoint1.example.com/bge-m3,https://endpoint2.example.com/bge-m3,https://endpoint3.example.com/bge-reranker-v2-m3"
        )
        assert args.static_models == "bge-m3,bge-m3,bge-reranker-v2-m3"
        assert args.static_model_types == "embeddings,embeddings,rerank"
        assert args.static_aliases == "text-embedding-3-small:bge-m3"


def test_load_initial_config_from_config_file_if_required_when_json_config_file_is_provided_adds_values_to_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.NamedTemporaryFile() as f:
        monkeypatch.setattr(sys, "argv", [sys.argv[0], "--dynamic-config-json", f.name])
        f.write(json.dumps({"routing_logic": "roundrobin"}).encode())
        f.seek(0)
        test_parser = argparse.ArgumentParser("test")
        test_parser.add_argument("--dynamic-config-yaml", type=str)
        test_parser.add_argument("--dynamic-config-json", type=str)
        args = test_parser.parse_args()
        args = parser.load_initial_config_from_config_file_if_required(
            test_parser, args
        )
        assert args.routing_logic == "roundrobin"


def test_load_initial_config_from_config_json_if_required_when_config_file_is_provided_does_not_override_cli_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.NamedTemporaryFile() as f:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                sys.argv[0],
                "--routing-logic",
                "roundrobin",
                "--dynamic-config-json",
                f.name,
            ],
        )
        f.write(json.dumps({"routing_logic": "testing"}).encode())
        f.seek(0)
        test_parser = argparse.ArgumentParser("test")
        test_parser.add_argument("--routing-logic", type=str)
        test_parser.add_argument("--dynamic-config-yaml", type=str)
        test_parser.add_argument("--dynamic-config-json", type=str)
        args = test_parser.parse_args()
        args = parser.load_initial_config_from_config_file_if_required(
            test_parser, args
        )
        assert args.routing_logic == "roundrobin"


def test_validate_args_when_service_discovery_is_set_to_static_and_static_backend_health_checks_is_set_and_static_model_types_is_not_set_raises_value_error() -> (
    None
):
    with pytest.raises(ValueError):
        parser.validate_args(
            MagicMock(
                routing_logic="roundrobin",
                service_discovery="static",
                static_backend_health_checks=True,
                static_model_types=None,
            )
        )


def test_validate_static_model_types_when_model_types_is_not_defines_raises_value_error() -> (
    None
):
    with pytest.raises(ValueError):
        parser.validate_static_model_types(None)


def test_validate_static_model_types_when_model_types_contains_unsupported_model_type_raises_value_error() -> (
    None
):
    with pytest.raises(ValueError):
        parser.validate_static_model_types("chat,unsupported")


def test_validate_static_model_types_when_model_types_contains_only_supported_model_types_does_not_raise_error() -> (
    None
):
    parser.validate_static_model_types("chat,completion,rerank,score")


def test_parse_args_log_format_defaults_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            sys.argv[0],
            "--service-discovery",
            "static",
            "--static-backends",
            "http://localhost:8000",
            "--static-models",
            "m1",
            "--routing-logic",
            "roundrobin",
        ],
    )
    args = parser.parse_args()
    assert args.log_format == "text"


def test_parse_args_log_format_accepts_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            sys.argv[0],
            "--service-discovery",
            "static",
            "--static-backends",
            "http://localhost:8000",
            "--static-models",
            "m1",
            "--routing-logic",
            "roundrobin",
            "--log-format",
            "json",
        ],
    )
    args = parser.parse_args()
    assert args.log_format == "json"


def _load_yaml_config(monkeypatch: pytest.MonkeyPatch, config: dict):
    with tempfile.NamedTemporaryFile() as f:
        monkeypatch.setattr(sys, "argv", [sys.argv[0], "--dynamic-config-yaml", f.name])
        f.write(yaml.safe_dump(config).encode())
        f.seek(0)
        test_parser = argparse.ArgumentParser("test")
        test_parser.add_argument("--dynamic-config-yaml", type=str)
        test_parser.add_argument("--dynamic-config-json", type=str)
        args = test_parser.parse_args()
        return parser.load_initial_config_from_config_file_if_required(
            test_parser, args
        )


def test_load_initial_config_when_yaml_models_set_max_model_len_adds_static_model_max_lens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _load_yaml_config(
        monkeypatch,
        {
            "service_discovery": "static",
            "static_models": {
                "llama3": {
                    "static_backends": ["http://a:8000", "http://b:8000"],
                    "max_model_len": 131072,
                },
                "qwen": {"static_backends": ["http://c:8000"]},
                "org/model": {
                    "static_backends": ["http://d:8000"],
                    "max_model_len": 32768,
                },
            },
        },
    )
    assert args.static_models == "llama3,llama3,org/model,qwen"  # safe_dump sorts keys
    assert args.static_model_max_lens == "llama3:131072,org/model:32768"


def test_load_initial_config_when_no_yaml_model_sets_max_model_len_leaves_it_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _load_yaml_config(
        monkeypatch,
        {"static_models": {"llama3": {"static_backends": ["http://a:8000"]}}},
    )
    assert getattr(args, "static_model_max_lens", None) is None


@pytest.mark.parametrize("value", ["131072", 0, True, 1.5])
def test_load_initial_config_when_yaml_max_model_len_is_not_a_positive_integer_raises_value_error(
    monkeypatch: pytest.MonkeyPatch, value
) -> None:
    with pytest.raises(ValueError, match="must be a positive integer"):
        _load_yaml_config(
            monkeypatch,
            {
                "static_models": {
                    "llama3": {
                        "static_backends": ["http://a:8000"],
                        "max_model_len": value,
                    }
                }
            },
        )


def test_validate_args_when_static_model_max_lens_names_unknown_model_raises_value_error() -> (
    None
):
    with pytest.raises(ValueError, match="not static models: typo"):
        parser.validate_args(
            MagicMock(
                routing_logic="roundrobin",
                service_discovery="static",
                static_backends="http://a:8000",
                static_models="llama3",
                static_backend_health_checks=False,
                static_model_max_lens="llama3:131072,typo:4096",
            )
        )
