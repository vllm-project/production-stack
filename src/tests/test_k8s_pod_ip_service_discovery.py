"""Unit tests for K8sPodIPServiceDiscovery._on_engine_update.

These tests focus on the pure event-handling logic of the pod-IP based
service discovery, in particular the MODIFIED branch that removes a stale
("ghost") endpoint when a pod's podIP is cleared by a node-pressure
eviction.

The real __init__ loads a kubeconfig and starts a watcher thread, so we
construct the instance with __new__ and inject only the attributes that
_on_engine_update touches.
"""

import threading
from unittest.mock import MagicMock

from vllm_router.service_discovery import EndpointInfo, K8sPodIPServiceDiscovery


def _make_discovery() -> K8sPodIPServiceDiscovery:
    d = K8sPodIPServiceDiscovery.__new__(K8sPodIPServiceDiscovery)
    d.available_engines = {}
    d.available_engines_lock = threading.Lock()
    d.known_models = set()
    d.known_models_lock = threading.Lock()
    d.namespace = "test-ns"
    d.port = "8000"
    return d


def _register(d: K8sPodIPServiceDiscovery, name: str) -> None:
    d.available_engines[name] = MagicMock(spec=EndpointInfo)


def test_modified_with_none_ip_removes_registered_engine():
    """Core regression: an evicted pod delivers MODIFIED with podIP=None.

    Before the fix this returned early and the endpoint lingered as a
    ghost; after the fix the registered endpoint is removed.
    """
    d = _make_discovery()
    _register(d, "pod-a")

    d._on_engine_update(
        engine_name="pod-a",
        engine_ip=None,
        event="MODIFIED",
        is_pod_ready=False,
        model_names=[],
        model_label=None,
    )

    assert "pod-a" not in d.available_engines


def test_modified_with_none_ip_unregistered_is_noop():
    """A Pending pod (not yet registered) with no IP must be skipped, not error."""
    d = _make_discovery()

    d._on_engine_update(
        engine_name="pending-pod",
        engine_ip=None,
        event="MODIFIED",
        is_pod_ready=False,
        model_names=[],
        model_label=None,
    )

    assert d.available_engines == {}


def test_added_with_none_ip_is_skipped():
    """ADDED with no IP (Pending pod) must not register anything.

    Confirms the ADDED branch is unchanged by the fix.
    """
    d = _make_discovery()
    d._add_engine = MagicMock()

    d._on_engine_update(
        engine_name="pending-pod",
        engine_ip=None,
        event="ADDED",
        is_pod_ready=False,
        model_names=[],
        model_label=None,
    )

    d._add_engine.assert_not_called()
    assert d.available_engines == {}


def test_modified_ready_with_ip_adds_engine():
    """MODIFIED with a real IP + ready + models must (re)add the engine."""
    d = _make_discovery()
    d._add_engine = MagicMock()

    d._on_engine_update(
        engine_name="pod-b",
        engine_ip="172.16.0.5",
        event="MODIFIED",
        is_pod_ready=True,
        model_names=["Qwen2.5-7B"],
        model_label="Qwen2.5-7B",
    )

    d._add_engine.assert_called_once_with(
        "pod-b", "172.16.0.5", ["Qwen2.5-7B"], "Qwen2.5-7B"
    )


def test_modified_not_ready_with_ip_removes_registered():
    """Graceful drain: a registered pod goes not-ready while its IP is still
    present. The existing (pre-fix) removal path must still work.
    """
    d = _make_discovery()
    _register(d, "pod-c")

    d._on_engine_update(
        engine_name="pod-c",
        engine_ip="172.16.0.9",
        event="MODIFIED",
        is_pod_ready=False,
        model_names=[],
        model_label=None,
    )

    assert "pod-c" not in d.available_engines
