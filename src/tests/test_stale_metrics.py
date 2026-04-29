import pytest
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest

from vllm_router.routers.metrics_router import _LABEL_GAUGES, _clear_label_gauges
from vllm_router.service_discovery import EndpointInfo
from vllm_router.services.metrics_service import (
    current_qps,
    gpu_prefix_cache_hit_rate,
    gpu_prefix_cache_hits_total,
    gpu_prefix_cache_queries_total,
    healthy_pods_total,
    num_requests_running,
)


def test_endpoint_info_healthy_defaults_to_true():
    ep = EndpointInfo(
        url="http://ep1:8000",
        model_names=["llama"],
        Id="id1",
        added_timestamp=0,
        model_label="default",
        sleep=False,
    )
    assert ep.healthy is True


def test_endpoint_info_healthy_can_be_set_false():
    ep = EndpointInfo(
        url="http://ep1:8000",
        model_names=["llama"],
        Id="id1",
        added_timestamp=0,
        model_label="default",
        sleep=False,
        healthy=False,
    )
    assert ep.healthy is False


@pytest.fixture(autouse=True)
def _reset_gauges():
    """Clear every label-based gauge before and after each test."""
    _clear_label_gauges()
    yield
    _clear_label_gauges()


def test_cleared_gauge_removes_stale_labels():
    """Stale server labels must disappear after _clear_label_gauges()."""
    # Simulate two active endpoints
    healthy_pods_total.labels(server="http://ep1:8000").set(1)
    healthy_pods_total.labels(server="http://ep2:8000").set(1)

    output = generate_latest(REGISTRY).decode()
    assert "ep1" in output
    assert "ep2" in output

    # Clear all labels (simulates start of /metrics handler)
    _clear_label_gauges()

    # Re-populate only ep1 (ep2 was removed from service discovery)
    healthy_pods_total.labels(server="http://ep1:8000").set(1)

    output = generate_latest(REGISTRY).decode()
    assert "ep1" in output
    assert "ep2" not in output


def test_clear_removes_all_labels_when_all_endpoints_gone():
    """When every endpoint is removed, no server labels remain."""
    current_qps.labels(server="http://ep1:8000").set(42)
    num_requests_running.labels(server="http://ep1:8000").set(3)

    _clear_label_gauges()

    output = generate_latest(REGISTRY).decode()
    assert "ep1" not in output


def test_clear_does_not_affect_unlabeled_gauges():
    """System gauges (CPU, memory, disk) have no labels and are unaffected."""
    from vllm_router.routers.metrics_router import router_cpu_usage_percent

    router_cpu_usage_percent.set(42.0)
    healthy_pods_total.labels(server="http://ep1:8000").set(1)

    _clear_label_gauges()

    output = generate_latest(REGISTRY).decode()
    assert "router_cpu_usage_percent" in output
    assert "42.0" in output


def test_label_gauges_list_contains_all_expected_gauges():
    """Ensure every gauge we export with a server label is in _LABEL_GAUGES."""
    expected = {
        current_qps,
        gpu_prefix_cache_hit_rate,
        gpu_prefix_cache_hits_total,
        gpu_prefix_cache_queries_total,
        healthy_pods_total,
        num_requests_running,
    }
    assert expected.issubset(set(_LABEL_GAUGES))


def test_repopulate_after_clear_shows_correct_values():
    """Values set after clear must reflect in Prometheus output."""
    _clear_label_gauges()

    healthy_pods_total.labels(server="http://new-ep:8000").set(1)
    current_qps.labels(server="http://new-ep:8000").set(99.5)

    output = generate_latest(REGISTRY).decode()
    assert "new-ep" in output
    assert "99.5" in output
