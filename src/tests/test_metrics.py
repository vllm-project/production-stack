from types import SimpleNamespace

from vllm_router.routers import metrics_router
from vllm_router.services.metrics_service import request_latency_seconds
from vllm_router.stats.engine_stats import EngineStats


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


async def test_metrics_exports_scraped_waiting_requests_and_kv_cache_usage(
    monkeypatch,
):
    server = "http://test-engine:8000"
    engine_stats = {
        server: EngineStats(num_queuing_requests=7, gpu_cache_usage_perc=0.42)
    }

    monkeypatch.setattr(
        metrics_router,
        "get_request_stats_monitor",
        lambda: SimpleNamespace(get_request_stats=lambda _: {}),
    )
    monkeypatch.setattr(
        metrics_router,
        "get_engine_stats_scraper",
        lambda: SimpleNamespace(get_engine_stats=lambda: engine_stats),
    )
    monkeypatch.setattr(
        metrics_router,
        "get_service_discovery",
        lambda: SimpleNamespace(get_endpoint_info=lambda: []),
    )

    response = await metrics_router.metrics()
    output = response.body.decode()

    assert f'vllm:num_requests_waiting{{server="{server}"}} 7.0' in output
    assert f'vllm:kv_cache_usage_perc{{server="{server}"}} 0.42' in output
