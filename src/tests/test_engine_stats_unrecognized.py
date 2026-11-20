from vllm_router.stats import engine_stats
from vllm_router.stats.engine_stats import EngineStats, EngineStatsScraper

# A well-formed Prometheus scrape whose metric names are not ones the router
# knows, e.g. a non-vLLM engine or a relabeling proxy in front of vLLM.
UNRECOGNIZED_SCRAPE = """# HELP sglang:num_running_reqs Number of running requests.
# TYPE sglang:num_running_reqs gauge
sglang:num_running_reqs{model_name="m"} 3.0
# HELP sglang:num_queue_reqs Number of queued requests.
# TYPE sglang:num_queue_reqs gauge
sglang:num_queue_reqs{model_name="m"} 1.0
"""

# A vLLM scrape that exports only some of the metrics the router reads.
PARTIAL_SCRAPE = """# HELP vllm:num_requests_running Number of requests in model execution batches.
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="m"} 2.0
"""


def test_scrape_without_recognized_metrics_returns_none():
    assert EngineStats.from_vllm_scrape(UNRECOGNIZED_SCRAPE) is None


def test_empty_scrape_returns_none():
    assert EngineStats.from_vllm_scrape("") is None


def test_partial_scrape_is_still_parsed():
    stats = EngineStats.from_vllm_scrape(PARTIAL_SCRAPE)
    assert stats is not None
    assert stats.num_running_requests == 2


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _bare_scraper():
    # Skip __init__, which starts the background scrape thread.
    scraper = object.__new__(EngineStatsScraper)
    scraper.scrape_interval = 1
    return scraper


def test_unrecognized_scrape_is_a_failed_scrape_and_warns(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        engine_stats.requests,
        "get",
        lambda url, timeout: _FakeResponse(UNRECOGNIZED_SCRAPE),
    )
    monkeypatch.setattr(engine_stats.logger, "warning", warnings.append)

    result = _bare_scraper()._scrape_one_endpoint("http://engine-1:8000")

    assert result is None
    assert len(warnings) == 1
    assert "http://engine-1:8000" in warnings[0]


def test_recognized_scrape_does_not_warn(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        engine_stats.requests,
        "get",
        lambda url, timeout: _FakeResponse(PARTIAL_SCRAPE),
    )
    monkeypatch.setattr(engine_stats.logger, "warning", warnings.append)

    result = _bare_scraper()._scrape_one_endpoint("http://engine-1:8000")

    assert result is not None
    assert warnings == []
