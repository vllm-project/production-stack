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
