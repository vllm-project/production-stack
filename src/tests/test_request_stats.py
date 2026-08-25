import pytest

from vllm_router.stats.request_stats import RequestStatsMonitor, SingletonMeta


@pytest.fixture(autouse=True)
def reset_request_stats_monitor():
    SingletonMeta._instances.pop(RequestStatsMonitor, None)
    yield
    SingletonMeta._instances.pop(RequestStatsMonitor, None)


def test_avg_decoding_length_tracks_decode_duration():
    monitor = RequestStatsMonitor(sliding_window_size=60)
    engine_url = "http://engine"

    monitor.on_new_request(engine_url, "request-1", 100.0)
    monitor.on_request_response(engine_url, "request-1", 101.0)
    assert monitor.get_request_stats(101.0)[engine_url].avg_decoding_length == -1

    monitor.on_request_complete(engine_url, "request-1", 105.0)
    assert monitor.get_request_stats(105.0)[engine_url].avg_decoding_length == 4.0
    assert monitor.get_request_stats(166.0)[engine_url].avg_decoding_length == -1
