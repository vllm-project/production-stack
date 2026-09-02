import logging

from vllm_router.stats.engine_stats import EngineStats

VLLM_SCRAPE = """
# HELP vllm:num_requests_running Number of running requests
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{model_name="llama"} 3.0
# HELP vllm:num_requests_waiting Number of waiting requests
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{model_name="llama"} 1.0
# HELP vllm:gpu_cache_usage_perc GPU KV cache usage
# TYPE vllm:gpu_cache_usage_perc gauge
vllm:gpu_cache_usage_perc{model_name="llama"} 0.5
"""

SGLANG_SCRAPE = """
# HELP sglang:num_running_reqs Number of running requests
# TYPE sglang:num_running_reqs gauge
sglang:num_running_reqs{model_name="llama"} 3.0
# HELP sglang:num_queue_reqs Number of queued requests
# TYPE sglang:num_queue_reqs gauge
sglang:num_queue_reqs{model_name="llama"} 1.0
"""


def test_from_vllm_scrape_parses_known_metrics(caplog):
    with caplog.at_level(logging.WARNING, logger="vllm_router.stats.engine_stats"):
        stats = EngineStats.from_vllm_scrape(VLLM_SCRAPE, "http://ep1:8000")
    assert stats.num_running_requests == 3.0
    assert stats.num_queuing_requests == 1.0
    assert stats.gpu_cache_usage_perc == 0.5
    assert len(caplog.records) == 0


def test_from_vllm_scrape_unrecognized_metrics_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="vllm_router.stats.engine_stats"):
        stats = EngineStats.from_vllm_scrape(SGLANG_SCRAPE, "http://ep2:8000")

    # The all-zero object is still returned (no behaviour change)...
    assert stats.num_running_requests == 0
    assert stats.num_queuing_requests == 0
    # ...but the silent failure is now logged loudly, naming the endpoint.
    assert any(
        "http://ep2:8000" in record.message
        and "sglang:num_running_reqs" in record.message
        for record in caplog.records
    )


def test_from_vllm_scrape_empty_payload_does_not_warn(caplog):
    with caplog.at_level(logging.WARNING, logger="vllm_router.stats.engine_stats"):
        stats = EngineStats.from_vllm_scrape("", "http://ep3:8000")

    assert stats.num_running_requests == 0
    assert len(caplog.records) == 0


def test_from_vllm_scrape_partial_match_does_not_warn(caplog):
    """A scrape with at least one recognized name is a partial success,
    not a total parse miss, so it should not trigger the loud warning."""
    mixed_scrape = VLLM_SCRAPE + SGLANG_SCRAPE
    with caplog.at_level(logging.WARNING, logger="vllm_router.stats.engine_stats"):
        stats = EngineStats.from_vllm_scrape(mixed_scrape, "http://ep4:8000")

    assert stats.num_running_requests == 3.0
    assert len(caplog.records) == 0
