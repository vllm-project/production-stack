import time

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from vllm_router.service_discovery import get_service_discovery
from vllm_router.services.metrics_service import (
    avg_decoding_length,
    avg_itl,
    avg_latency,
    current_qps,
    healthy_pods_total,
    num_decoding_requests,
    num_prefill_requests,
    num_requests_running,
    num_requests_swapped,
)
from vllm_router.stats.request_stats import get_request_stats_monitor

metrics_router = APIRouter()


# --- Prometheus Metrics Endpoint ---
@metrics_router.get("/metrics")
async def metrics():
    # Retrieve request stats from the monitor.
    """
    Endpoint to expose Prometheus metrics for the vLLM router.

    This function gathers request statistics, engine metrics, and health status
    of the service endpoints to update Prometheus gauges. It exports metrics
    such as queries per second (QPS), average decoding length, number of prefill
    and decoding requests, average latency, average inter-token latency, number
    of swapped requests, and the number of healthy pods for each server. The
    metrics are used to monitor the performance and health of the vLLM router
    services.

    Returns:
        Response: A HTTP response containing the latest Prometheus metrics in
        the appropriate content type.
    """

    stats = get_request_stats_monitor().get_request_stats(time.time())
    for server, stat in stats.items():
        current_qps.labels(server=server).set(stat.qps)
        # Assuming stat contains the following attributes:
        avg_decoding_length.labels(server=server).set(stat.avg_decoding_length)
        num_prefill_requests.labels(server=server).set(stat.in_prefill_requests)
        num_decoding_requests.labels(server=server).set(stat.in_decoding_requests)
        num_requests_running.labels(server=server).set(
            stat.in_prefill_requests + stat.in_decoding_requests
        )
        avg_latency.labels(server=server).set(stat.avg_latency)
        avg_itl.labels(server=server).set(stat.avg_itl)
        num_requests_swapped.labels(server=server).set(stat.num_swapped_requests)
    # For healthy pods, we use a hypothetical function from service discovery.
    healthy = {}
    endpoints = get_service_discovery().get_endpoint_info()
    for ep in endpoints:
        # Assume each endpoint object has an attribute 'healthy' (1 if healthy, 0 otherwise).
        healthy[ep.url] = 1 if getattr(ep, "healthy", True) else 0
    for server, value in healthy.items():
        healthy_pods_total.labels(server=server).set(value)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
