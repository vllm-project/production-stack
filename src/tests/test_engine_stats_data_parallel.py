"""EngineStats of a data-parallel vLLM engine (one sample per DP engine)."""

from vllm_router.stats.engine_stats import EngineStats


def _scrape(per_engine):
    lines = [
        "# TYPE vllm:num_requests_running gauge",
        "# TYPE vllm:num_requests_waiting gauge",
        "# TYPE vllm:gpu_cache_usage_perc gauge",
        "# TYPE vllm:gpu_prefix_cache_hits counter",
        "# TYPE vllm:gpu_prefix_cache_queries counter",
    ]
    for engine, (running, waiting, usage, hits, queries) in enumerate(per_engine):
        labels = f'{{engine="{engine}",model_name="m"}}'
        lines += [
            f"vllm:num_requests_running{labels} {running}",
            f"vllm:num_requests_waiting{labels} {waiting}",
            f"vllm:gpu_cache_usage_perc{labels} {usage}",
            f"vllm:gpu_prefix_cache_hits_total{labels} {hits}",
            f"vllm:gpu_prefix_cache_queries_total{labels} {queries}",
        ]
    return "\n".join(lines) + "\n"


def test_single_engine_unchanged():
    stats = EngineStats.from_vllm_scrape(_scrape([(3, 1, 0.42, 10, 20)]))
    assert stats.num_running_requests == 3
    assert stats.num_queuing_requests == 1
    assert abs(stats.gpu_cache_usage_perc - 0.42) < 1e-9
    assert stats.gpu_prefix_cache_hits_total == 10
    assert stats.gpu_prefix_cache_queries_total == 20
    assert abs(stats.gpu_prefix_cache_hit_rate - 0.5) < 1e-9


def test_data_parallel_engines_aggregated():
    # --data-parallel-size 8: the last sample alone made the pod look 8x less loaded.
    per_engine = [(i, 1, 0.1 * (i % 2), 10, 20) for i in range(8)]
    stats = EngineStats.from_vllm_scrape(_scrape(per_engine))
    assert stats.num_running_requests == sum(range(8))
    assert stats.num_queuing_requests == 8
    assert abs(stats.gpu_cache_usage_perc - 0.05) < 1e-9
    assert stats.gpu_prefix_cache_hits_total == 80
    assert stats.gpu_prefix_cache_queries_total == 160
    assert abs(stats.gpu_prefix_cache_hit_rate - 0.5) < 1e-9


def test_hit_rate_from_totals_not_mean_of_engine_rates():
    # Engine 0: 1 query, 0 hits; engine 1: 1000 queries, 1000 hits.
    stats = EngineStats.from_vllm_scrape(
        _scrape([(0, 0, 0.0, 0, 1), (0, 0, 0.0, 1000, 1000)])
    )
    assert abs(stats.gpu_prefix_cache_hit_rate - 1000 / 1001) < 1e-9


def test_empty_scrape():
    stats = EngineStats.from_vllm_scrape("")
    assert stats.num_running_requests == 0
    assert stats.gpu_cache_usage_perc == 0.0
