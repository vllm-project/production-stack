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
    stats = EngineStats.from_vllm_scrape(SCRAPE.format(name="vllm:gpu_cache_usage_perc"))
    assert stats.gpu_cache_usage_perc == 0.42
