import threading
from unittest.mock import MagicMock

from vllm_router.service_discovery import K8sServiceNameServiceDiscovery


def _make_discovery() -> K8sServiceNameServiceDiscovery:
    """Build an instance without running __init__ (which starts a k8s watcher)."""
    instance = K8sServiceNameServiceDiscovery.__new__(K8sServiceNameServiceDiscovery)
    instance.namespace = "default"
    instance.known_models = set()
    instance.known_models_lock = threading.Lock()
    instance._service_to_model = {}
    instance.k8s_api = MagicMock()
    return instance


def test_track_known_model_records_model_from_added_event():
    discovery = _make_discovery()

    discovery._track_known_model("svc-a", "ADDED", "llama3")

    assert discovery.has_ever_seen_model("llama3") is True
    assert discovery.has_ever_seen_model("unknown") is False


def test_track_known_model_reads_selector_when_label_missing():
    discovery = _make_discovery()
    svc = MagicMock()
    svc.spec.selector = {"model": "llama3"}
    discovery.k8s_api.read_namespaced_service.return_value = svc

    discovery._track_known_model("svc-a", "ADDED", None)

    discovery.k8s_api.read_namespaced_service.assert_called_once_with(
        "svc-a", "default"
    )
    assert discovery.has_ever_seen_model("llama3") is True


def test_track_known_model_ignores_service_without_model_selector():
    discovery = _make_discovery()
    svc = MagicMock()
    svc.spec.selector = {"app": "vllm"}
    discovery.k8s_api.read_namespaced_service.return_value = svc

    discovery._track_known_model("svc-a", "ADDED", None)

    assert discovery.known_models == set()


def test_track_known_model_ignores_k8s_api_failure():
    discovery = _make_discovery()
    discovery.k8s_api.read_namespaced_service.side_effect = RuntimeError("boom")

    discovery._track_known_model("svc-a", "ADDED", None)

    assert discovery.known_models == set()


def test_track_known_model_deleted_event_drops_last_reference():
    discovery = _make_discovery()
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "DELETED", None)

    assert discovery.has_ever_seen_model("llama3") is False
    assert discovery._service_to_model == {}


def test_track_known_model_deleted_event_keeps_label_while_other_service_references_it():
    discovery = _make_discovery()
    discovery._track_known_model("svc-a", "ADDED", "llama3")
    discovery._track_known_model("svc-b", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "DELETED", None)

    assert discovery.has_ever_seen_model("llama3") is True
    assert discovery._service_to_model == {"svc-b": "llama3"}


def test_track_known_model_modified_event_updates_mapping():
    discovery = _make_discovery()
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "MODIFIED", "llama3-v2")

    assert discovery.has_ever_seen_model("llama3-v2") is True
    assert discovery._service_to_model == {"svc-a": "llama3-v2"}
