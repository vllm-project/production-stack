from unittest.mock import Mock

import pytest

from vllm_router.stats import engine_stats
from vllm_router.stats.engine_stats import EngineStatsScraper
from vllm_router.utils import SingletonMeta


@pytest.fixture
def scraper_class():
    # Use a fresh singleton type so these tests cannot affect the global scraper.
    class TestScraper(EngineStatsScraper):
        pass

    yield TestScraper
    SingletonMeta._instances.pop(TestScraper, None)


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_does_not_start_thread(monkeypatch, scraper_class, interval):
    thread = Mock()
    monkeypatch.setattr(engine_stats.threading, "Thread", thread)
    with pytest.raises(ValueError, match="finite and greater than 0"):
        scraper_class(interval)
    thread.assert_not_called()


@pytest.mark.parametrize("interval", [0.1, 0.5, 1, 1.5, 2.5])
def test_sleep_preserves_interval(monkeypatch, scraper_class, interval):
    thread = Mock()
    monkeypatch.setattr(engine_stats.threading, "Thread", thread)
    scraper = scraper_class(interval)
    thread.return_value.start.assert_called_once_with()
    now = [0.0]
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr(engine_stats.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(engine_stats.time, "sleep", sleep)
    scraper._sleep_or_break()
    assert sum(sleeps) == pytest.approx(interval)
    assert all(0 < delay <= 1 for delay in sleeps)


def test_sleep_stops_after_shutdown(monkeypatch, scraper_class):
    monkeypatch.setattr(engine_stats.threading, "Thread", Mock())
    scraper = scraper_class(30)
    sleeps = []

    def sleep(delay):
        sleeps.append(delay)
        scraper.running = False

    monkeypatch.setattr(engine_stats.time, "sleep", sleep)
    scraper._sleep_or_break()
    assert sleeps == [1]
