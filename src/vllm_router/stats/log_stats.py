import time

from fastapi import FastAPI

from vllm_router.log import init_logger
from vllm_router.service_discovery import get_service_discovery
from vllm_router.services.metrics_service import (
    avg_decoding_length,
    avg_itl,
    avg_latency,
    current_qps,
    num_decoding_requests,
    num_prefill_requests,
    num_requests_running,
    num_requests_swapped,
)

logger = init_logger(__name__)


def log_stats(app: FastAPI, interval: int = 10):
    """
    Periodically logs the engine and request statistics for each service endpoint.

    This function retrieves the current service endpoints and their corresponding
    engine and request statistics, and logs them at a specified interval. The
    statistics include the number of running and queued requests, GPU cache hit
    rate, queries per second (QPS), average latency, average inter-token latency
    (ITL), and more. These statistics are also updated in the Prometheus metrics.

    Args:
        app (FastAPI): FastAPI application
        interval (int): The interval in seconds at which statistics are logged.
            Default is 10 seconds.
    """

    while True:
        time.sleep(interval)
        logstr = "\n" + "=" * 50 + "\n"
        endpoints = get_service_discovery().get_endpoint_info()
        engine_stats = app.state.engine_stats_scraper.get_engine_stats()
        request_stats = app.state.request_stats_monitor.get_request_stats(time.time())
        for endpoint in endpoints:
            url = endpoint.url
            logstr += f"Model: {endpoint.model_name}\n"
            logstr += f"Server: {url}\n"
            if url in engine_stats:
                es = engine_stats[url]
                logstr += (
                    f" Engine Stats: Running Requests: {es.num_running_requests}, "
                    f"Queued Requests: {es.num_queuing_requests}, "
                    f"GPU Cache Hit Rate: {es.gpu_prefix_cache_hit_rate:.2f}\n"
                )
            else:
                logstr += " Engine Stats: No stats available\n"
            if url in request_stats:
                rs = request_stats[url]
                logstr += (
                    f" Request Stats: QPS: {rs.qps:.2f}, "
                    f"Avg Latency: {rs.avg_latency}, "
                    f"Avg ITL: {rs.avg_itl}, "
                    f"Prefill Requests: {rs.in_prefill_requests}, "
                    f"Decoding Requests: {rs.in_decoding_requests}, "
                    f"Swapped Requests: {rs.num_swapped_requests}, "
                    f"Finished: {rs.finished_requests}, "
                    f"Uptime: {rs.uptime:.2f} sec\n"
                )
                current_qps.labels(server=url).set(rs.qps)
                avg_decoding_length.labels(server=url).set(rs.avg_decoding_length)
                num_prefill_requests.labels(server=url).set(rs.in_prefill_requests)
                num_decoding_requests.labels(server=url).set(rs.in_decoding_requests)
                num_requests_running.labels(server=url).set(
                    rs.in_prefill_requests + rs.in_decoding_requests
                )
                avg_latency.labels(server=url).set(rs.avg_latency)
                avg_itl.labels(server=url).set(rs.avg_itl)
                num_requests_swapped.labels(server=url).set(rs.num_swapped_requests)
            else:
                logstr += " Request Stats: No stats available\n"
            logstr += "-" * 50 + "\n"
        logstr += "=" * 50 + "\n"
        logger.info(logstr)
