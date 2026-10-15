import pytest

from vllm_router.stats.engine_stats import EngineStats


def counters(prefix, hits=208, queries=408):
    return f"""# TYPE vllm:{prefix}_hits_total counter
vllm:{prefix}_hits_total{{engine="0",model_name="m"}} {hits}
# TYPE vllm:{prefix}_queries_total counter
vllm:{prefix}_queries_total{{engine="0",model_name="m"}} {queries}
"""


@pytest.mark.parametrize("prefix", ["gpu_prefix_cache", "prefix_cache"])
def test_counter_names_and_derived_hit_ratio(prefix):
    stats = EngineStats.from_vllm_scrape(counters(prefix))
    assert stats.gpu_prefix_cache_hits_total == 208
    assert stats.gpu_prefix_cache_queries_total == 408
    assert stats.gpu_prefix_cache_hit_rate == pytest.approx(208 / 408)


@pytest.mark.parametrize("gauge", [0.0, 0.73])
def test_explicit_legacy_gauge_is_preserved(gauge):
    scrape = counters("prefix_cache") + (
        "# TYPE vllm:gpu_prefix_cache_hit_rate gauge\n"
        f'vllm:gpu_prefix_cache_hit_rate{{model_name="m"}} {gauge}\n'
    )
    assert EngineStats.from_vllm_scrape(scrape).gpu_prefix_cache_hit_rate == gauge


@pytest.mark.parametrize(
    "scrape",
    [
        "",
        counters("prefix_cache", 0, 0),
        counters("gpu_prefix_cache", 0, 0),
        "vllm:prefix_cache_hits_total 1\n",
        "vllm:prefix_cache_queries_total 20\n",
    ],
)
def test_absent_or_zero_query_count_has_zero_hit_ratio(scrape):
    assert EngineStats.from_vllm_scrape(scrape).gpu_prefix_cache_hit_rate == 0


@pytest.mark.parametrize("reverse", [False, True])
def test_current_counter_names_take_precedence_without_double_counting(reverse):
    parts = [counters("prefix_cache", 8, 10), counters("gpu_prefix_cache", 1, 10)]
    stats = EngineStats.from_vllm_scrape("".join(reversed(parts) if reverse else parts))
    assert stats.gpu_prefix_cache_hits_total == 8
    assert stats.gpu_prefix_cache_queries_total == 10
    assert stats.gpu_prefix_cache_hit_rate == pytest.approx(0.8)


def test_counter_reset_uses_current_scrape():
    before = EngineStats.from_vllm_scrape(counters("prefix_cache", 80, 100))
    after = EngineStats.from_vllm_scrape(counters("prefix_cache", 1, 10))
    assert before.gpu_prefix_cache_hit_rate == pytest.approx(0.8)
    assert after.gpu_prefix_cache_hit_rate == pytest.approx(0.1)


def test_unrelated_request_and_kv_metrics_are_preserved():
    stats = EngineStats.from_vllm_scrape(
        counters("prefix_cache")
        + (
            "vllm:num_requests_running 3\nvllm:num_requests_waiting 2\n"
            "vllm:kv_cache_usage_perc 0.42\n"
        )
    )
    assert stats.num_running_requests == 3
    assert stats.num_queuing_requests == 2
    assert stats.gpu_cache_usage_perc == 0.42
