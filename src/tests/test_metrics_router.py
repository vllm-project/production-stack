from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from vllm_router.routers import metrics_router as mr
from vllm_router.stats.request_stats import RequestStatsMonitor


@pytest.mark.asyncio
async def test_metrics_reads_cpu_percent_without_interval():
    RequestStatsMonitor(60)
    scraper = MagicMock()
    scraper.get_engine_stats.return_value = {}
    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = []
    app = FastAPI()
    app.include_router(mr.metrics_router)

    with (
        patch.object(mr, "get_engine_stats_scraper", return_value=scraper),
        patch.object(mr, "get_service_discovery", return_value=service_discovery),
        patch.object(mr.psutil, "cpu_percent", return_value=12.5) as cpu_percent,
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://router"
        ) as client:
            response = await client.get("/metrics")

    assert response.status_code == 200
    # A positive interval sleeps inside the async handler and stalls the router.
    cpu_percent.assert_called_once_with(interval=None)
    assert "router_cpu_usage_percent 12.5" in response.text
