"""Unit tests for RequestStatsMonitor completion accounting.

`on_request_complete` is the only place avg_latency is written. It must
use the caller-supplied timestamp (so a delayed monitor call does not
inflate the sample) and must drop per-request bookkeeping so the
(engine_url, request_id) maps cannot grow without bound.
"""

import pytest

from vllm_router.stats.request_stats import (
    RequestStatsMonitor,
    SingletonMeta,
    initialize_request_stats_monitor,
)


@pytest.fixture
def monitor():
    if RequestStatsMonitor in SingletonMeta._instances:
        del SingletonMeta._instances[RequestStatsMonitor]
    mon = initialize_request_stats_monitor(sliding_window_size=60.0)
    yield mon
    if RequestStatsMonitor in SingletonMeta._instances:
        del SingletonMeta._instances[RequestStatsMonitor]


URL = "http://10.0.0.1:8000"


def test_avg_latency_uses_the_supplied_completion_timestamp(monitor):
    """A later wall-clock read must not change the recorded latency.

    process_request() passes end_time into on_request_complete; using
    time.time() inside the monitor would add whatever delay sits between
    that capture and the method body.
    """
    monitor.on_new_request(URL, "req-1", timestamp=100.0)
    monitor.on_request_response(URL, "req-1", timestamp=100.2)
    monitor.on_request_complete(URL, "req-1", timestamp=101.5)

    stats = monitor.get_request_stats(current_time=101.5)
    assert stats[URL].avg_latency == pytest.approx(1.5)
    assert stats[URL].avg_decoding_length == pytest.approx(1.3)


def test_completed_request_is_dropped_from_per_request_maps(monitor):
    monitor.on_new_request(URL, "req-1", timestamp=10.0)
    monitor.on_request_response(URL, "req-1", timestamp=10.1)
    assert (URL, "req-1") in monitor.request_start_time
    assert (URL, "req-1") in monitor.first_token_time

    monitor.on_request_complete(URL, "req-1", timestamp=11.0)
    assert (URL, "req-1") not in monitor.request_start_time
    assert (URL, "req-1") not in monitor.first_token_time


def test_complete_without_start_does_not_raise(monitor):
    monitor.on_request_complete(URL, "never-seen", timestamp=1.0)
    stats = monitor.get_request_stats(current_time=1.0)
    assert stats[URL].finished_requests == 1
    assert stats[URL].avg_latency == -1
    assert stats[URL].avg_decoding_length == -1


def test_complete_before_first_token_leaves_decoding_length_unset(monitor):
    monitor.on_new_request(URL, "req-1", timestamp=10.0)
    monitor.on_request_complete(URL, "req-1", timestamp=10.4)
    stats = monitor.get_request_stats(current_time=10.4)
    assert stats[URL].avg_latency == pytest.approx(0.4)
    assert stats[URL].avg_decoding_length == -1
