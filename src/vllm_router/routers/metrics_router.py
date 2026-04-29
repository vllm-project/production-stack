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

import psutil
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

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
    healthy_pods_total,
    num_decoding_requests,
    num_prefill_requests,
    num_requests_running,
    num_requests_swapped,
)
from vllm_router.stats.engine_stats import get_engine_stats_scraper
from vllm_router.stats.request_stats import get_request_stats_monitor

logger = init_logger(__name__)

metrics_router = APIRouter()

router_cpu_usage_percent = Gauge(
    "router_cpu_usage_percent",
    "CPU usage percent",
)
router_memory_usage_percent = Gauge(
    "router_memory_usage_percent",
    "Memory usage percent",
)
router_disk_usage_percent = Gauge(
    "router_disk_usage_percent",
    "Disk usage percent",
)


_LABEL_GAUGES = [
    current_qps,
    avg_decoding_length,
    num_prefill_requests,
    num_decoding_requests,
    num_requests_running,
    avg_latency,
    avg_itl,
    num_requests_swapped,
    gpu_prefix_cache_hit_rate,
    gpu_prefix_cache_hits_total,
    gpu_prefix_cache_queries_total,
    healthy_pods_total,
]


def _clear_label_gauges() -> None:
    for gauge in _LABEL_GAUGES:
        gauge.clear()


@metrics_router.get("/metrics")
async def metrics():
    _clear_label_gauges()

    cpu_percent = psutil.cpu_percent(interval=0.1)
    router_cpu_usage_percent.set(cpu_percent)

    memory_percent = psutil.virtual_memory().percent
    router_memory_usage_percent.set(memory_percent)

    disk_percent = psutil.disk_usage("/").percent
    router_disk_usage_percent.set(disk_percent)

    stats = get_request_stats_monitor().get_request_stats(time.time())
    for server, stat in stats.items():
        current_qps.labels(server=server).set(stat.qps)
        avg_decoding_length.labels(server=server).set(stat.avg_decoding_length)
        num_prefill_requests.labels(server=server).set(stat.in_prefill_requests)
        num_decoding_requests.labels(server=server).set(stat.in_decoding_requests)
        num_requests_running.labels(server=server).set(
            stat.in_prefill_requests + stat.in_decoding_requests
        )
        avg_latency.labels(server=server).set(stat.avg_latency)
        avg_itl.labels(server=server).set(stat.avg_itl)
        num_requests_swapped.labels(server=server).set(stat.num_swapped_requests)

    engine_stats = get_engine_stats_scraper().get_engine_stats()
    for server, engine_stat in engine_stats.items():
        gpu_prefix_cache_hit_rate.labels(server=server).set(
            engine_stat.gpu_prefix_cache_hit_rate
        )
        gpu_prefix_cache_hits_total.labels(server=server).set(
            engine_stat.gpu_prefix_cache_hits_total
        )
        gpu_prefix_cache_queries_total.labels(server=server).set(
            engine_stat.gpu_prefix_cache_queries_total
        )

    endpoints = get_service_discovery().get_endpoint_info()
    for ep in endpoints:
        healthy_pods_total.labels(server=ep.url).set(1 if ep.healthy else 0)

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
