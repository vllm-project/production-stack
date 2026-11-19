"""Unit tests for --enable-sleep-mode detection across command and args."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from vllm_router.service_discovery import (
    K8sPodIPServiceDiscovery,
    _container_enables_sleep_mode,
)


def _container(command, args=None):
    return SimpleNamespace(command=command, args=args)


def test_missing_command_is_treated_as_enabled():
    assert _container_enables_sleep_mode(_container(None)) is True
    assert _container_enables_sleep_mode(_container([])) is True


def test_flag_in_command():
    assert (
        _container_enables_sleep_mode(
            _container(["vllm", "serve", "my-model", "--enable-sleep-mode"])
        )
        is True
    )


def test_command_without_flag_is_disabled():
    assert _container_enables_sleep_mode(_container(["vllm", "serve"])) is False


def test_operator_extra_args_shape_enables_sleep_mode():
    # VLLMRuntime: Command ["vllm", "serve"], ExtraArgs appended to args.
    assert (
        _container_enables_sleep_mode(
            _container(
                ["/opt/venv/bin/vllm", "serve"],
                ["my-model", "--port", "8000", "--enable-sleep-mode"],
            )
        )
        is True
    )


def test_shell_wrapper_splits_whitespace():
    assert (
        _container_enables_sleep_mode(
            _container(["sh", "-c"], ["vllm serve my-model --enable-sleep-mode"])
        )
        is True
    )


def test_no_enable_sleep_mode_is_not_a_match():
    assert (
        _container_enables_sleep_mode(
            _container(["vllm", "serve", "--no-enable-sleep-mode"])
        )
        is False
    )
    assert (
        _container_enables_sleep_mode(
            _container(["vllm", "serve"], ["--no-enable-sleep-mode"])
        )
        is False
    )


def _pod_ip_discovery(command, args=None) -> K8sPodIPServiceDiscovery:
    d = K8sPodIPServiceDiscovery.__new__(K8sPodIPServiceDiscovery)
    d.namespace = "default"
    container = MagicMock()
    container.name = "vllm"
    container.command = command
    container.args = args
    pod = MagicMock()
    pod.spec.containers = [container]
    d.k8s_api = MagicMock()
    d.k8s_api.read_namespaced_pod.return_value = pod
    return d


def test_pod_ip_discovery_reads_flag_from_args():
    d = _pod_ip_discovery(
        ["/opt/venv/bin/vllm", "serve"],
        ["my-model", "--port", "8000", "--enable-sleep-mode"],
    )
    assert d._check_engine_sleep_mode("e") is True


def test_pod_ip_discovery_reads_flag_from_shell_wrapper():
    d = _pod_ip_discovery(["sh", "-c"], ["vllm serve my-model --enable-sleep-mode"])
    assert d._check_engine_sleep_mode("e") is True


def test_pod_ip_discovery_flag_in_command_still_works():
    d = _pod_ip_discovery(["vllm", "serve", "my-model", "--enable-sleep-mode"])
    assert d._check_engine_sleep_mode("e") is True


def test_pod_ip_discovery_command_without_flag_is_disabled():
    d = _pod_ip_discovery(["vllm", "serve"])
    assert d._check_engine_sleep_mode("e") is False
