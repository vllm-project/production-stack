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
        "pod-b", "172.16.0.5", ["Qwen2.5-7B"], "Qwen2.5-7B", None
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


# ---------------------------------------------------------------------------
# Reconciliation on watch reconnect
#
# The watch stream is the only source of removals, so a DELETED event lost
# during a disconnect leaves a ghost engine. Listing before each stream repairs
# it, and the watch starts at the list's resourceVersion so nothing slips
# between the two calls. Since the watch no longer replays ADDED events, the
# reconciliation is also the startup discovery path.
# ---------------------------------------------------------------------------


def _make_pod(
    name,
    ip="10.0.0.1",
    ready=True,
    terminating=False,
    labels=None,
    annotations=None,
):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.labels = {} if labels is None else labels
    pod.metadata.annotations = {} if annotations is None else annotations
    pod.metadata.deletion_timestamp = (
        None if not terminating else "2026-01-01T00:00:00Z"
    )
    pod.status.pod_ip = ip
    pod.status.container_statuses = [MagicMock(ready=ready)]
    return pod


def _make_reconciler(pods, engines=None):
    d = _make_discovery()
    d.label_selector = "environment=test"
    d.available_engines = engines or {}
    d.k8s_api = MagicMock()
    d.k8s_api.list_namespaced_pod.return_value = MagicMock(
        items=pods, metadata=MagicMock(resource_version="4242")
    )
    d._get_model_names = MagicMock(return_value=["m"])
    d._get_model_label = MagicMock(
        side_effect=lambda pod: (pod.metadata.labels or {}).get("model")
    )
    d._add_engine = MagicMock()
    return d


def _registered(
    url="http://10.0.0.1:8000", model_label=None, sleep=False, lora_modified=None
):
    known = MagicMock(spec=EndpointInfo)
    known.url = url
    known.model_label = model_label
    known.sleep = sleep
    known.lora_modified = lora_modified
    return known


def test_reconcile_drops_engine_whose_pod_is_gone():
    """Core regression: the DELETED event was missed, the list must repair it."""
    d = _make_reconciler(
        pods=[_make_pod("pod-alive")],
        engines={
            "pod-gone": _registered(url="http://10.0.0.9:8000"),
            "pod-alive": _registered(),
        },
    )

    d._reconcile_engines()

    assert "pod-gone" not in d.available_engines
    assert "pod-alive" in d.available_engines


def test_reconcile_discovers_pods_at_startup():
    """The watch no longer replays ADDED, so the list must populate the table."""
    d = _make_reconciler(
        pods=[_make_pod("pod-a", ip="10.0.0.1"), _make_pod("pod-b", ip="10.0.0.2")]
    )

    d._reconcile_engines()

    assert {c.args[0] for c in d._add_engine.call_args_list} == {"pod-a", "pod-b"}


def test_reconcile_skips_unchanged_pod():
    """A ready pod already registered at the same URL must not be re-queried."""
    d = _make_reconciler(pods=[_make_pod("pod-a")], engines={"pod-a": _registered()})

    d._reconcile_engines()

    d._get_model_names.assert_not_called()
    d._add_engine.assert_not_called()


def test_reconcile_drops_pod_that_became_not_ready():
    """A readiness change missed during the disconnect must still be applied."""
    d = _make_reconciler(
        pods=[_make_pod("pod-a", ready=False)], engines={"pod-a": _registered()}
    )

    d._reconcile_engines()

    assert "pod-a" not in d.available_engines


def test_reconcile_drops_pod_with_cleared_ip():
    """An evicted pod keeps its object but loses its IP."""
    d = _make_reconciler(
        pods=[_make_pod("pod-a", ip=None)], engines={"pod-a": _registered()}
    )

    d._reconcile_engines()

    assert "pod-a" not in d.available_engines


def test_reconcile_rehandles_pod_whose_sleep_label_changed():
    """/sleep patches the pod; missing that event would keep routing to it."""
    d = _make_reconciler(
        pods=[_make_pod("pod-a", labels={"sleeping": "true"})],
        engines={"pod-a": _registered(sleep=False)},
    )

    d._reconcile_engines()

    d._add_engine.assert_called_once()


def test_reconcile_rehandles_pod_whose_lora_annotation_changed():
    """The LoRA operator stamps the pod when it loads or unloads an adapter.

    Nothing else about the pod moves, so missing that event during a
    disconnect would leave the router serving a stale adapter list.
    """
    d = _make_reconciler(
        pods=[
            _make_pod("pod-a", annotations={"lora-modified": "2026-01-01T00:00:01Z"})
        ],
        engines={"pod-a": _registered(lora_modified="2026-01-01T00:00:00Z")},
    )

    d._reconcile_engines()

    d._add_engine.assert_called_once_with(
        "pod-a", "10.0.0.1", ["m"], None, "2026-01-01T00:00:01Z"
    )


def test_reconcile_returns_the_list_resource_version():
    """The watch must start where the list stopped, leaving no gap."""
    d = _make_reconciler(pods=[_make_pod("pod-a")], engines={"pod-a": _registered()})

    assert d._reconcile_engines() == "4242"


def test_reconcile_survives_one_broken_pod():
    """One unreachable pod must not abort discovery for the others."""
    d = _make_reconciler(
        pods=[_make_pod("pod-bad", ip="10.0.0.1"), _make_pod("pod-ok", ip="10.0.0.2")]
    )
    d._get_model_names = MagicMock(
        side_effect=lambda ip: (
            (_ for _ in ()).throw(RuntimeError("unreachable"))
            if ip == "10.0.0.1"
            else ["m"]
        )
    )

    d._reconcile_engines()

    assert [c.args[0] for c in d._add_engine.call_args_list] == ["pod-ok"]
