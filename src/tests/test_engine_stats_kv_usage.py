from vllm_router.stats.engine_stats import EngineStats

SCRAPE = """# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{{engine="0",model_name="m"}} 3.0
# HELP {name} KV-cache usage. 1 means 100 percent usage.
# TYPE {name} gauge
{name}{{engine="0",model_name="m"}} 0.42
"""


def test_kv_cache_usage_perc_is_read():
    stats = EngineStats.from_vllm_scrape(SCRAPE.format(name="vllm:kv_cache_usage_perc"))
    assert stats.gpu_cache_usage_perc == 0.42
    assert stats.num_running_requests == 3


def test_legacy_gpu_cache_usage_perc_is_still_read():
    stats = EngineStats.from_vllm_scrape(
        SCRAPE.format(name="vllm:gpu_cache_usage_perc")
    )
    assert stats.gpu_cache_usage_perc == 0.42


DP_SCRAPE = """# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="m"} 5.0
vllm:num_requests_running{engine="1",model_name="m"} 1.0
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{engine="0",model_name="m"} 2.0
vllm:num_requests_waiting{engine="1",model_name="m"} 4.0
# HELP vllm:gpu_prefix_cache_hits_total Prefix cache hits.
# TYPE vllm:gpu_prefix_cache_hits_total counter
vllm:gpu_prefix_cache_hits_total{engine="0",model_name="m"} 10.0
vllm:gpu_prefix_cache_hits_total{engine="1",model_name="m"} 30.0
# HELP vllm:gpu_prefix_cache_queries_total Prefix cache queries.
# TYPE vllm:gpu_prefix_cache_queries_total counter
vllm:gpu_prefix_cache_queries_total{engine="0",model_name="m"} 20.0
vllm:gpu_prefix_cache_queries_total{engine="1",model_name="m"} 40.0
# HELP vllm:kv_cache_usage_perc KV-cache usage. 1 means 100 percent usage.
# TYPE vllm:kv_cache_usage_perc gauge
vllm:kv_cache_usage_perc{engine="0",model_name="m"} 0.9
vllm:kv_cache_usage_perc{engine="1",model_name="m"} 0.1
"""


def test_data_parallel_engines_are_aggregated():
    stats = EngineStats.from_vllm_scrape(DP_SCRAPE)
    assert stats.num_running_requests == 6
    assert stats.num_queuing_requests == 6
    assert stats.gpu_prefix_cache_hits_total == 40
    assert stats.gpu_prefix_cache_queries_total == 60
    assert stats.gpu_prefix_cache_hit_rate == 40 / 60
    assert stats.gpu_cache_usage_perc == 0.9
