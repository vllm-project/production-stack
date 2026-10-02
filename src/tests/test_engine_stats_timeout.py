"""Tests for the engine-stats scrape read timeout being configurable
independently of the scrape interval."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.parsers import parser
from vllm_router.stats import engine_stats
from vllm_router.utils import SingletonMeta


@pytest.fixture(autouse=True)
def _reset_singleton():
    SingletonMeta._instances.pop(engine_stats.EngineStatsScraper, None)
    yield
    SingletonMeta._instances.pop(engine_stats.EngineStatsScraper, None)


def _make_scraper(*args, **kwargs) -> engine_stats.EngineStatsScraper:
    # The scraper starts a background thread that needs service discovery; the
    # tests here only care about the resolved timeout, so keep it off-thread.
    with patch.object(engine_stats.threading, "Thread", MagicMock()):
        return engine_stats.EngineStatsScraper(*args, **kwargs)


def test_scrape_timeout_defaults_to_scrape_interval() -> None:
    scraper = _make_scraper(30)
    assert scraper.scrape_interval == 30
    assert scraper.scrape_timeout == 30


def test_scrape_timeout_none_defaults_to_scrape_interval() -> None:
    assert _make_scraper(30, None).scrape_timeout == 30


def test_scrape_timeout_overrides_scrape_interval() -> None:
    scraper = _make_scraper(10, 90.5)
    assert scraper.scrape_interval == 10
    assert scraper.scrape_timeout == 90.5


def test_scrape_one_endpoint_uses_scrape_timeout() -> None:
    scraper = _make_scraper(10, 90.5)
    response = MagicMock(text="")
    with patch.object(engine_stats.requests, "get", return_value=response) as get:
        scraper._scrape_one_endpoint("http://engine:8000")
    assert get.call_args.kwargs["timeout"] == (3.05, 90.5)


def test_initialize_engine_stats_scraper_passes_timeout() -> None:
    with patch.object(engine_stats.threading, "Thread", MagicMock()):
        scraper = engine_stats.initialize_engine_stats_scraper(10, 90.5)
    assert scraper.scrape_timeout == 90.5


def test_parser_engine_stats_scrape_timeout_defaults_to_none() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--engine-stats-scrape-timeout", type=float, default=None)
    assert p.parse_args([]).engine_stats_scrape_timeout is None


def test_validate_args_rejects_non_positive_scrape_timeout() -> None:
    args_mock = MagicMock(
        service_discovery="static",
        static_backends="http://engine:8000",
        static_models="model",
        static_backend_health_checks=False,
        routing_logic="roundrobin",
        log_stats=False,
        engine_stats_interval=30,
        engine_stats_scrape_timeout=0,
        request_stats_window=60,
        sentry_traces_sample_rate=0.0,
        sentry_profile_session_sample_rate=0.0,
    )
    with pytest.raises(
        ValueError, match="Engine stats scrape timeout must be greater than 0."
    ):
        parser.validate_args(args_mock)


def test_validate_args_accepts_unset_scrape_timeout() -> None:
    args_mock = MagicMock(
        service_discovery="static",
        static_backends="http://engine:8000",
        static_models="model",
        static_backend_health_checks=False,
        routing_logic="roundrobin",
        log_stats=False,
        engine_stats_interval=30,
        engine_stats_scrape_timeout=None,
        request_stats_window=60,
        sentry_traces_sample_rate=0.0,
        sentry_profile_session_sample_rate=0.0,
    )
    parser.validate_args(args_mock)
