from unittest.mock import MagicMock

import pytest
from kubernetes import client

from vllm_router.service_discovery import (
    K8sPodIPServiceDiscovery,
    K8sServiceNameServiceDiscovery,
    _is_stale_resource_version_error,
)

K8sDiscoveryClass = (
    type[K8sPodIPServiceDiscovery] | type[K8sServiceNameServiceDiscovery]
)


@pytest.fixture
def k8s_discovery_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock K8s dependencies so service discovery can be unit-tested."""
    monkeypatch.setattr(
        "vllm_router.service_discovery.config.load_incluster_config",
        MagicMock(),
    )
    monkeypatch.setattr(
        "vllm_router.service_discovery.config.load_kube_config",
        MagicMock(),
    )
    monkeypatch.setattr(
        "vllm_router.service_discovery.client.CoreV1Api",
        MagicMock(),
    )
    monkeypatch.setattr(
        "vllm_router.service_discovery.threading.Thread",
        MagicMock(),
    )
    monkeypatch.setattr(
        "vllm_router.service_discovery.time.sleep",
        lambda _: None,
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Timeout: Too large resource version: 123, current: 456", True),
        ("410 Gone: too old resource version", True),
        ("resourceVersion is too old", True),
        ("TOO LARGE RESOURCE VERSION", True),
        ("connection refused", False),
        ("Unexpected error", False),
        ("", False),
    ],
)
def test_is_stale_resource_version_error(message: str, expected: bool) -> None:
    assert _is_stale_resource_version_error(Exception(message)) is expected


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        (410, "Gone", True),
        (504, "Timeout: Too large resource version: 1, current: 2", True),
        (504, "Gateway timeout", False),
        (500, "Internal server error", False),
    ],
)
def test_is_stale_resource_version_error_with_api_exception(
    status: int,
    reason: str,
    expected: bool,
) -> None:
    """410 is unconditionally stale; 504 only when the message matches."""
    exc = client.rest.ApiException(status=status, reason=reason)
    assert _is_stale_resource_version_error(exc) is expected


def _run_watcher_recovery(
    discovery_class: K8sDiscoveryClass,
    monkeypatch: pytest.MonkeyPatch,
    k8s_discovery_setup: None,
    stale_message: str,
) -> None:
    """Drive a K8s discovery instance through one stale error and recovery."""
    watch_cls = MagicMock()
    first_watcher = MagicMock()
    second_watcher = MagicMock()
    watch_cls.side_effect = [first_watcher, second_watcher]
    monkeypatch.setattr(
        "vllm_router.service_discovery.watch.Watch",
        watch_cls,
    )

    discovery = discovery_class(
        app=None,
        namespace="default",
        port="8000",
        label_selector="model=test",
    )

    calls = 0

    def first_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise Exception(stale_message)

    def second_stream(*args, **kwargs):
        nonlocal calls
        calls += 1
        discovery.running = False
        return iter([])

    first_watcher.stream.side_effect = first_stream
    second_watcher.stream.side_effect = second_stream

    discovery.running = True
    discovery._watch_engines()

    assert watch_cls.call_count == 2
    assert first_watcher.stream.call_count == 1
    assert second_watcher.stream.call_count == 1


def test_k8s_pod_ip_service_discovery_recovers_from_stale_resource_version(
    monkeypatch: pytest.MonkeyPatch,
    k8s_discovery_setup: None,
) -> None:
    _run_watcher_recovery(
        K8sPodIPServiceDiscovery,
        monkeypatch,
        k8s_discovery_setup,
        "Timeout: Too large resource version: 123, current: 456",
    )


def test_k8s_service_name_service_discovery_recovers_from_stale_resource_version(
    monkeypatch: pytest.MonkeyPatch,
    k8s_discovery_setup: None,
) -> None:
    _run_watcher_recovery(
        K8sServiceNameServiceDiscovery,
        monkeypatch,
        k8s_discovery_setup,
        "410 Gone: too old resource version",
    )


def test_k8s_watcher_does_not_reset_on_unrelated_errors(
    monkeypatch: pytest.MonkeyPatch,
    k8s_discovery_setup: None,
) -> None:
    watch_cls = MagicMock()
    watcher = MagicMock()
    watch_cls.return_value = watcher
    monkeypatch.setattr(
        "vllm_router.service_discovery.watch.Watch",
        watch_cls,
    )

    discovery = K8sPodIPServiceDiscovery(
        app=None,
        namespace="default",
        port="8000",
        label_selector="model=test",
    )

    calls = 0

    def stream_side_effect(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("connection refused")
        discovery.running = False
        return iter([])

    watcher.stream.side_effect = stream_side_effect

    discovery.running = True
    discovery._watch_engines()

    assert watch_cls.call_count == 1
    assert calls == 2
