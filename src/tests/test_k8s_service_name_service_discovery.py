"""Unit tests for K8sServiceNameServiceDiscovery reconciliation.

Same failure mode as the pod-IP class: the watch stream is the only source of
removals, so a DELETED event lost during a disconnect leaves a ghost engine.
Listing before each stream repairs it and provides the resourceVersion the
watch starts from.

The real __init__ loads a kubeconfig and starts a watcher thread, so we build
the instance with __new__ and inject only what the tested code touches.
"""

import threading
from unittest.mock import MagicMock

from vllm_router.service_discovery import EndpointInfo, K8sServiceNameServiceDiscovery


def _make_service(name):
    svc = MagicMock()
    svc.metadata.name = name
    svc.metadata.labels = {}
    return svc


def _make_reconciler(services, engines=None, ready=True):
    d = K8sServiceNameServiceDiscovery.__new__(K8sServiceNameServiceDiscovery)
    d.available_engines = engines or {}
    d.available_engines_lock = threading.Lock()
    d.known_models = set()
    d.known_models_lock = threading.Lock()
    d.namespace = "test-ns"
    d.port = "8000"
    d.label_selector = "environment=test"
    d.k8s_api = MagicMock()
    d.k8s_api.list_namespaced_service.return_value = MagicMock(
        items=services, metadata=MagicMock(resource_version="99")
    )
    d._check_service_ready = MagicMock(return_value=ready)
    d._get_model_names = MagicMock(return_value=["m"])
    d._get_model_label = MagicMock(return_value=None)
    d._add_engine = MagicMock()
    return d


def _registered():
    known = MagicMock(spec=EndpointInfo)
    known.url = "http://svc-a:8000"
    return known


def test_reconcile_drops_engine_whose_service_is_gone():
    d = _make_reconciler(
        services=[_make_service("svc-a")],
        engines={"svc-gone": _registered(), "svc-a": _registered()},
    )

    d._reconcile_engines()

    assert "svc-gone" not in d.available_engines
    assert "svc-a" in d.available_engines


def test_reconcile_discovers_services_at_startup():
    """The watch no longer replays ADDED, so the list must populate the table."""
    d = _make_reconciler(services=[_make_service("svc-a"), _make_service("svc-b")])

    d._reconcile_engines()

    assert {c.args[0] for c in d._add_engine.call_args_list} == {"svc-a", "svc-b"}


def test_reconcile_skips_ready_registered_service():
    d = _make_reconciler(
        services=[_make_service("svc-a")], engines={"svc-a": _registered()}
    )

    d._reconcile_engines()

    d._get_model_names.assert_not_called()


def test_reconcile_survives_one_broken_service():
    """A Service with no Endpoints object must not abort the whole pass."""
    d = _make_reconciler(services=[_make_service("svc-bad"), _make_service("svc-ok")])
    d._check_service_ready = MagicMock(
        side_effect=lambda name, ns: (
            (_ for _ in ()).throw(RuntimeError("404")) if name == "svc-bad" else True
        )
    )

    d._reconcile_engines()

    assert [c.args[0] for c in d._add_engine.call_args_list] == ["svc-ok"]


def test_reconcile_returns_the_list_resource_version():
    d = _make_reconciler(services=[], engines={})

    assert d._reconcile_engines() == "99"
