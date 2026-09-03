from types import SimpleNamespace

from vllm_router.routers.routing_logic import RoutingDecision
from vllm_router.services.metrics_service import (
    record_routing_decision,
    request_latency_seconds,
    routing_decisions_total,
)
from vllm_router.services.request_service.request import _record_backend_selection


def test_records_both_status_labels():
    request_latency_seconds.labels(
        server="http://test-engine:8000", model="test-model", status="success"
    ).observe(0.5)
    request_latency_seconds.labels(
        server="http://test-engine:8000", model="test-model", status="error"
    ).observe(30.0)

    statuses_seen = {
        s.labels.get("status")
        for metric in request_latency_seconds.collect()
        for s in metric.samples
        if s.name == "vllm:request_latency_seconds_bucket"
        and s.labels.get("server") == "http://test-engine:8000"
    }

    assert {"success", "error"} <= statuses_seen


def test_routing_counter_uses_bounded_labels_without_raw_url_or_model():
    raw_url = "http://secret-backend.internal:8000"

    record_routing_decision(
        algorithm="user-supplied-algorithm",
        decision="user-supplied-decision",
        reason=raw_url,
    )

    samples = [
        sample
        for metric in routing_decisions_total.collect()
        for sample in metric.samples
        if sample.name == "vllm:routing_decisions_total"
        and sample.labels.get("algorithm") == "unknown"
        and sample.labels.get("decision") == "unknown"
        and sample.labels.get("reason") == "unknown"
    ]
    assert len(samples) == 1
    assert samples[0].labels == {
        "algorithm": "unknown",
        "decision": "unknown",
        "reason": "unknown",
    }
    assert raw_url not in str(samples[0].labels)
    assert "model" not in samples[0].labels


def test_arbitrary_endpoint_ids_do_not_create_routing_metric_series():
    for index in range(10_000):
        url = f"http://backend-{index}.internal:8000"
        selection = RoutingDecision(
            url,
            algorithm="disaggregated_prefill_orchestrated",
            decision="retry",
            reason="missing_session",
        )
        _record_backend_selection(
            selection,
            [SimpleNamespace(url=url, Id=f"discovered-id-{index}")],
        )

    samples = [
        sample
        for metric in routing_decisions_total.collect()
        for sample in metric.samples
        if sample.name == "vllm:routing_decisions_total"
        and sample.labels.get("algorithm") == "disaggregated_prefill_orchestrated"
        and sample.labels.get("decision") == "retry"
        and sample.labels.get("reason") == "missing_session"
    ]

    assert len(samples) == 1
    assert samples[0].labels == {
        "algorithm": "disaggregated_prefill_orchestrated",
        "decision": "retry",
        "reason": "missing_session",
    }
