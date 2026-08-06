import threading
from unittest.mock import MagicMock, patch

from vllm_router.stats.engine_stats import EngineStats, EngineStatsScraper


def make_scraper():
    scraper = object.__new__(EngineStatsScraper)
    scraper.engine_stats = {}
    scraper.engine_stats_lock = threading.Lock()
    scraper.scrape_interval = 30.0
    scraper.admission_scrape_interval = 1.0
    scraper.on_metrics_update = None
    scraper.running = False
    scraper._stop_event = threading.Event()
    return scraper


def test_queue_only_scrape_merges_waiting_count_without_mutating_existing_stats():
    scraper = make_scraper()
    existing_stats = EngineStats(
        num_running_requests=7,
        num_queuing_requests=2,
        gpu_prefix_cache_hit_rate=0.2,
        gpu_prefix_cache_hits_total=11,
        gpu_prefix_cache_queries_total=17,
        gpu_cache_usage_perc=0.5,
    )
    scraper.engine_stats = {"http://engine1": existing_stats}
    scraped_stats = EngineStats(
        num_running_requests=99,
        num_queuing_requests=5,
        gpu_prefix_cache_hit_rate=0.9,
        gpu_prefix_cache_hits_total=99,
        gpu_prefix_cache_queries_total=99,
        gpu_cache_usage_perc=0.9,
    )

    endpoint = MagicMock(url="http://engine1")
    with (
        patch(
            "vllm_router.stats.engine_stats.get_service_discovery",
            return_value=MagicMock(
                get_endpoint_info=MagicMock(return_value=[endpoint])
            ),
        ),
        patch.object(scraper, "_scrape_one_endpoint", return_value=scraped_stats),
    ):
        scraper._scrape_metrics(queue_only=True)

    updated_stats = scraper.engine_stats["http://engine1"]
    assert updated_stats is not existing_stats
    assert updated_stats.num_queuing_requests == 5
    assert updated_stats.num_running_requests == 7
    assert updated_stats.gpu_prefix_cache_hit_rate == 0.2
    assert updated_stats.gpu_prefix_cache_hits_total == 11
    assert updated_stats.gpu_prefix_cache_queries_total == 17
    assert updated_stats.gpu_cache_usage_perc == 0.5


def test_scrape_one_endpoint_uses_mode_specific_timeout():
    scraper = make_scraper()
    mock_response = MagicMock()
    mock_response.text = ""
    mock_response.raise_for_status.return_value = None

    with (
        patch(
            "vllm_router.stats.engine_stats.requests.get", return_value=mock_response
        ) as mock_get,
        patch(
            "vllm_router.stats.engine_stats.EngineStats.from_vllm_scrape",
            return_value=EngineStats(),
        ),
    ):
        scraper._scrape_one_endpoint("http://engine1", queue_only=False)
        scraper._scrape_one_endpoint("http://engine1", queue_only=True)

    assert mock_get.call_args_list[0].kwargs["timeout"] == scraper.scrape_interval
    assert (
        mock_get.call_args_list[1].kwargs["timeout"]
        == scraper.admission_scrape_interval
    )


def _scrape(scraper, endpoint_urls, scrape_fn, queue_only):
    endpoints = [MagicMock(url=u) for u in endpoint_urls]
    with (
        patch(
            "vllm_router.stats.engine_stats.get_service_discovery",
            return_value=MagicMock(get_endpoint_info=MagicMock(return_value=endpoints)),
        ),
        patch.object(scraper, "_scrape_one_endpoint", side_effect=scrape_fn),
    ):
        scraper._scrape_metrics(queue_only=queue_only)


def test_queue_only_scrape_does_not_evict_endpoint_that_failed_to_respond():
    """An admission scrape uses a tight timeout, so a transient miss must not
    drop the endpoint's full stats until the next full scrape."""
    scraper = make_scraper()
    healthy = EngineStats(num_running_requests=7, num_queuing_requests=2)
    scraper.engine_stats = {"http://engine1": healthy, "http://engine2": healthy}

    def flaky(url, queue_only=False):
        if url == "http://engine1":
            return None  # timed out
        return EngineStats(num_running_requests=99, num_queuing_requests=5)

    _scrape(scraper, ["http://engine1", "http://engine2"], flaky, queue_only=True)

    assert "http://engine1" in scraper.engine_stats
    assert scraper.engine_stats["http://engine1"] == healthy
    assert scraper.engine_stats["http://engine2"].num_queuing_requests == 5
    assert scraper.engine_stats["http://engine2"].num_running_requests == 7


def test_queue_only_scrape_does_not_insert_unknown_endpoint():
    """Endpoints discovered since the last full scrape are left to it, so a
    partially-filled record is never published."""
    scraper = make_scraper()
    scraper.engine_stats = {}

    _scrape(
        scraper,
        ["http://new-engine"],
        lambda url, queue_only=False: EngineStats(num_queuing_requests=4),
        queue_only=True,
    )

    assert scraper.engine_stats == {}


def test_full_scrape_still_reconciles_membership():
    """Membership reconciliation remains the full scrape's job."""
    scraper = make_scraper()
    scraper.engine_stats = {"http://gone": EngineStats(num_running_requests=1)}

    _scrape(
        scraper,
        ["http://engine1"],
        lambda url, queue_only=False: EngineStats(num_running_requests=3),
        queue_only=False,
    )

    assert "http://gone" not in scraper.engine_stats
    assert scraper.engine_stats["http://engine1"].num_running_requests == 3
