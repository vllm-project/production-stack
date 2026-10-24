from dataclasses import fields
from pathlib import Path

import pytest

from vllm_router.stats.engine_stats import EngineStats

VLLM_SCRAPE = Path(__file__).parent / "fixtures" / "vllm_v0.32.0_metrics.txt"

PREFIX_CACHE_NOT_READ = pytest.mark.xfail(
    strict=True, reason="vllm:prefix_cache_* is not read yet (#1140)"
)

EXPECTED = [
    pytest.param("num_running_requests", 3),
    pytest.param("num_queuing_requests", 2),
    pytest.param("gpu_cache_usage_perc", 0.42),
    pytest.param("gpu_prefix_cache_hits_total", 208, marks=PREFIX_CACHE_NOT_READ),
    pytest.param("gpu_prefix_cache_queries_total", 408, marks=PREFIX_CACHE_NOT_READ),
    pytest.param(
        "gpu_prefix_cache_hit_rate",
        pytest.approx(208 / 408),
        marks=PREFIX_CACHE_NOT_READ,
    ),
]


@pytest.fixture(scope="module")
def stats():
    return EngineStats.from_vllm_scrape(VLLM_SCRAPE.read_text())


@pytest.mark.parametrize("field,expected", EXPECTED)
def test_field_is_read_from_current_vllm_scrape(stats, field, expected):
    assert getattr(stats, field) == expected


def test_contract_covers_every_engine_stats_field():
    assert {param.values[0] for param in EXPECTED} == {
        field.name for field in fields(EngineStats)
    }
