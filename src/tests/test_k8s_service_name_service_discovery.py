import threading

import pytest

from vllm_router.service_discovery import K8sServiceNameServiceDiscovery


@pytest.fixture
def discovery() -> K8sServiceNameServiceDiscovery:
    """Build an instance without running __init__ (which starts a k8s watcher)."""
    instance = K8sServiceNameServiceDiscovery.__new__(K8sServiceNameServiceDiscovery)
    instance.namespace = "default"
    instance.known_models = set()
    instance.known_models_lock = threading.Lock()
    instance._service_to_model = {}
    return instance


def test_track_known_model_records_model_from_added_event(discovery):
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    assert discovery.has_ever_seen_model("llama3") is True
    assert discovery.has_ever_seen_model("unknown") is False


def test_track_known_model_ignores_event_without_model_label(discovery):
    discovery._track_known_model("svc-a", "ADDED", None)
    discovery._track_known_model("svc-b", "ADDED", "")

    assert discovery.known_models == set()
    assert discovery._service_to_model == {}


def test_track_known_model_deleted_event_drops_last_reference(discovery):
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "DELETED", None)

    assert discovery.has_ever_seen_model("llama3") is False
    assert discovery._service_to_model == {}


def test_track_known_model_deleted_event_keeps_label_while_other_service_references_it(
    discovery,
):
    discovery._track_known_model("svc-a", "ADDED", "llama3")
    discovery._track_known_model("svc-b", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "DELETED", None)

    assert discovery.has_ever_seen_model("llama3") is True
    assert discovery._service_to_model == {"svc-b": "llama3"}


def test_track_known_model_deleted_event_for_unknown_service_is_noop(discovery):
    discovery._track_known_model("svc-ghost", "DELETED", None)

    assert discovery.known_models == set()
    assert discovery._service_to_model == {}


def test_track_known_model_relabel_drops_stale_label(discovery):
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "MODIFIED", "llama3-v2")

    assert discovery.has_ever_seen_model("llama3-v2") is True
    assert discovery.has_ever_seen_model("llama3") is False
    assert discovery._service_to_model == {"svc-a": "llama3-v2"}


def test_track_known_model_relabel_keeps_old_label_when_another_service_references_it(
    discovery,
):
    discovery._track_known_model("svc-a", "ADDED", "llama3")
    discovery._track_known_model("svc-b", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "MODIFIED", "llama3-v2")

    assert discovery.has_ever_seen_model("llama3") is True
    assert discovery.has_ever_seen_model("llama3-v2") is True
    assert discovery._service_to_model == {"svc-a": "llama3-v2", "svc-b": "llama3"}


def test_track_known_model_modified_event_removing_label_drops_stale(discovery):
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "MODIFIED", None)

    assert discovery.has_ever_seen_model("llama3") is False
    assert discovery._service_to_model == {}


def test_track_known_model_modified_event_removing_label_keeps_other_references(
    discovery,
):
    discovery._track_known_model("svc-a", "ADDED", "llama3")
    discovery._track_known_model("svc-b", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "MODIFIED", None)

    assert discovery.has_ever_seen_model("llama3") is True
    assert discovery._service_to_model == {"svc-b": "llama3"}


def test_track_known_model_modified_event_with_same_label_is_noop(discovery):
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    discovery._track_known_model("svc-a", "MODIFIED", "llama3")

    assert discovery._service_to_model == {"svc-a": "llama3"}
    assert discovery.known_models == {"llama3"}


def test_get_known_models_returns_snapshot_copy(discovery):
    discovery._track_known_model("svc-a", "ADDED", "llama3")

    snapshot = discovery.get_known_models()
    snapshot.add("injected")

    assert discovery.known_models == {"llama3"}
