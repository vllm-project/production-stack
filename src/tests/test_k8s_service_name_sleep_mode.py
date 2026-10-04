"""Unit tests for K8sServiceNameServiceDiscovery._check_engine_sleep_mode.

A container that does not override the image entrypoint has
``container.command is None``, which is an ordinary deployment. The pod-IP
class already guards that case; these tests pin the same behaviour here.

The real __init__ loads a kubeconfig and starts a watcher thread, so the
instance is built with __new__ and given only the attributes the method
touches, the same way test_k8s_pod_ip_service_discovery.py does.
"""

from unittest.mock import MagicMock

from vllm_router.service_discovery import K8sServiceNameServiceDiscovery


def _make_discovery(command) -> K8sServiceNameServiceDiscovery:
    d = K8sServiceNameServiceDiscovery.__new__(K8sServiceNameServiceDiscovery)
    d.namespace = "test-ns"

    container = MagicMock()
    container.name = "vllm"
    container.command = command

    pod = MagicMock()
    pod.spec.containers = [container]

    pods = MagicMock()
    pods.items = [pod]

    service = MagicMock()
    service.spec.selector = {"app": "vllm"}

    d.k8s_api = MagicMock()
    d.k8s_api.read_namespaced_service.return_value = service
    d.k8s_api.list_namespaced_pod.return_value = pods
    return d


def test_no_explicit_command_is_treated_as_sleep_mode_enabled():
    d = _make_discovery(None)
    assert d._check_engine_sleep_mode("svc") is True


def test_explicit_command_with_the_flag_enables_sleep_mode():
    d = _make_discovery(["vllm", "serve", "--enable-sleep-mode"])
    assert d._check_engine_sleep_mode("svc") is True


def test_explicit_command_without_the_flag_disables_sleep_mode():
    d = _make_discovery(["vllm", "serve"])
    assert d._check_engine_sleep_mode("svc") is False
