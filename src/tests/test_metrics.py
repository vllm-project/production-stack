import asyncio
import time

import pytest

from vllm_router.routers import metrics_router as metrics_module
from vllm_router.services.metrics_service import request_latency_seconds
from vllm_router.stats.request_stats import RequestStatsMonitor, SingletonMeta


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


@pytest.fixture
def _initialized_monitor():
    SingletonMeta._instances.pop(RequestStatsMonitor, None)
    RequestStatsMonitor(sliding_window_size=10)
    yield
    SingletonMeta._instances.pop(RequestStatsMonitor, None)


def test_metrics_scrape_does_not_block_the_event_loop(
    monkeypatch, _initialized_monitor
):
    # psutil.cpu_percent(interval=0.1) slept synchronously inside the async
    # handler, pausing all in-flight proxying for ~100 ms on every Prometheus
    # scrape (#1236).
    class _EmptyScraper:
        def get_engine_stats(self):
            return {}

    class _EmptyDiscovery:
        def get_endpoint_info(self):
            return []

    monkeypatch.setattr(
        metrics_module, "get_engine_stats_scraper", lambda: _EmptyScraper()
    )
    monkeypatch.setattr(
        metrics_module, "get_service_discovery", lambda: _EmptyDiscovery()
    )

    asyncio.run(metrics_module.metrics())  # warm-up scrape

    start = time.perf_counter()
    asyncio.run(metrics_module.metrics())
    elapsed = time.perf_counter() - start

    assert elapsed < 0.06, f"/metrics blocked the loop for {elapsed * 1000:.0f} ms"
