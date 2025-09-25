# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import time

from fastapi import FastAPI

from vllm_router.log import init_logger
from vllm_router.service_discovery import get_service_discovery
from vllm_router.services.metrics_service import (
    avg_decoding_length,
    avg_itl,
    avg_latency,
    current_qps,
    gpu_prefix_cache_hit_rate,
    gpu_prefix_cache_hits_total,
    gpu_prefix_cache_queries_total,
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
            logstr += f"Server: {url}\n"
            if endpoint.model_info:
                logstr += "Models:\n"
                for model_id, model_info in endpoint.model_info.items():
                    logstr += f"  - {model_id}"
                    if model_info.parent:
                        logstr += f" (adapter for {model_info.parent})"
                    logstr += "\n"
            else:
                logstr += "Models: No model information available\n"
            if url in engine_stats:
                es = engine_stats[url]
                logstr += (
                    f" Engine Stats: Running Requests: {es.num_running_requests}, "
                    f"Queued Requests: {es.num_queuing_requests}, "
                    f"GPU Cache Hit Rate: {es.gpu_prefix_cache_hit_rate:.2f}\n"
                )
                gpu_prefix_cache_hit_rate.labels(server=url).set(
                    es.gpu_prefix_cache_hit_rate
                )
                gpu_prefix_cache_hits_total.labels(server=url).set(
                    es.gpu_prefix_cache_hits_total
                )
                gpu_prefix_cache_queries_total.labels(server=url).set(
                    es.gpu_prefix_cache_queries_total
                )
            else:
                logstr += " Engine Stats: No stats available\n"
            if url in request_stats:
                rs = request_stats[url]
                logstr += (
                    f" Request Stats: QPS: {rs.qps:.2f}, "
                    f"Avg Latency: {rs.avg_latency:.2f}, "
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
