from dataclasses import fields
from pathlib import Path

import pytest

from vllm_router.stats.engine_stats import EngineStats

VLLM_SCRAPE = Path(__file__).parent / "fixtures" / "vllm_v0.32.0_metrics.txt"

PREFIX_CACHE_NOT_READ = pytest.mark.xfail(
    strict=True, reason="vllm:prefix_cache_* is not read yet (#1140)"
)

EXPECTED_MAP = {
    "num_running_requests": (3, ()),
    "num_queuing_requests": (2, ()),
    "gpu_cache_usage_perc": (0.42, ()),
    "gpu_prefix_cache_hits_total": (208, (PREFIX_CACHE_NOT_READ,)),
    "gpu_prefix_cache_queries_total": (408, (PREFIX_CACHE_NOT_READ,)),
    "gpu_prefix_cache_hit_rate": (pytest.approx(208 / 408), (PREFIX_CACHE_NOT_READ,)),
}

EXPECTED = [
    pytest.param(field, value, marks=marks)
    for field, (value, marks) in EXPECTED_MAP.items()
]


@pytest.fixture(scope="module")
def stats():
    return EngineStats.from_vllm_scrape(VLLM_SCRAPE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field,expected", EXPECTED)
def test_field_is_read_from_current_vllm_scrape(stats, field, expected):
    assert getattr(stats, field) == expected


def test_contract_covers_every_engine_stats_field():
    assert set(EXPECTED_MAP) == {field.name for field in fields(EngineStats)}
