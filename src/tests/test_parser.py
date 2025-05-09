import argparse
import json
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

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


def test_load_initial_config_from_config_json_if_required_when_config_file_is_not_provided_returns_args_without_changes() -> (
    None
):
    args_mock = MagicMock(example=True, dynamic_config_json=None)
    assert (
        parser.load_initial_config_from_config_json_if_required(MagicMock(), args_mock)
        == args_mock
    )


def test_load_initial_config_from_config_json_if_required_when_config_file_is_provided_adds_values_to_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.NamedTemporaryFile() as f:
        monkeypatch.setattr(sys, "argv", [sys.argv[0], "--dynamic-config-json", f.name])
        f.write(json.dumps({"routing_logic": "roundrobin"}).encode())
        f.seek(0)
        test_parser = argparse.ArgumentParser("test")
        test_parser.add_argument("--routing-logic", type=str)
        test_parser.add_argument("--dynamic-config-json", type=str)
        args = test_parser.parse_args()
        args = parser.load_initial_config_from_config_json_if_required(
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
        test_parser.add_argument("--dynamic-config-json", type=str)
        args = test_parser.parse_args()
        args = parser.load_initial_config_from_config_json_if_required(
            test_parser, args
        )
        assert args.routing_logic == "roundrobin"
