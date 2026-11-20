"""Unit tests for --enable-sleep-mode detection across command and args."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vllm_router.service_discovery import (
    K8sPodIPServiceDiscovery,
    _container_enables_sleep_mode,
)


@pytest.mark.parametrize(("command", "args"), [(None, None), ([], ["--port", "8000"])])
def test_image_defaults_allow_sleep_probe(command, args):
    container = SimpleNamespace(command=command, args=args)
    assert _container_enables_sleep_mode(container) is True


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on", "y", "t"])
def test_truthy_assignment_enables_sleep_mode(value):
    container = SimpleNamespace(
        command=["vllm", "serve"], args=[f"--enable-sleep-mode={value}"]
    )
    assert _container_enables_sleep_mode(container) is True


@pytest.mark.parametrize(
    "flag",
    [
        "--enable-sleep-mode=false",
        "--enable-sleep-mode=0",
        "--enable-sleep-mode=",
        "--enable-sleep-mode=unknown",
        "--no_enable_sleep_mode",
    ],
)
def test_last_flag_in_args_disables_sleep_mode(flag):
    container = SimpleNamespace(
        command=["vllm", "serve", "--enable-sleep-mode"], args=[flag]
    )
    assert _container_enables_sleep_mode(container) is False


def test_last_flag_in_shell_wrapper_enables_sleep_mode():
    container = SimpleNamespace(
        command=["sh", "-c"],
        args=["vllm serve my-model --enable-sleep-mode=false --enable_sleep_mode"],
    )
    assert _container_enables_sleep_mode(container) is True


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--enable-sleep-mode"], True),
        (["--model", "x"], True),
        (["--no-enable-sleep-mode"], False),
    ],
)
def test_pod_ip_discovery_reads_image_entrypoint_args(args, expected):
    discovery = K8sPodIPServiceDiscovery.__new__(K8sPodIPServiceDiscovery)
    discovery.namespace = "default"
    discovery.k8s_api = MagicMock()
    pod = discovery.k8s_api.read_namespaced_pod.return_value
    pod.spec.containers = [SimpleNamespace(name="vllm", command=None, args=args)]

    assert discovery._check_engine_sleep_mode("e") is expected
