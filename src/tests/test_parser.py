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
    args_mock = MagicMock(routing_logic="roundrobin", service_discovery=None)
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
