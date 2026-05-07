from vllm_router.services.metrics_service import request_latency_seconds


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
