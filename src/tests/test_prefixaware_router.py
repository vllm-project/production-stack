from collections import Counter
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from vllm_router.routers.routing_logic import (
    PrefixAwareRouter,
    cleanup_routing_logic,
)


@pytest.fixture(autouse=True)
def cleanup_router():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


class EndpointInfo:
    def __init__(self, url: str):
        self.url = url


class RequestStats:
    def __init__(self, qps: float):
        self.qps = qps


class EngineStats:
    def __init__(self, num_running_requests: int = 0, num_queuing_requests: int = 0):
        self.num_running_requests = num_running_requests
        self.num_queuing_requests = num_queuing_requests


class Request:
    def __init__(self, headers: Dict[str, str], body: Dict[str, Any] = None):
        self.headers = headers
        self.body = body


@pytest.mark.asyncio
async def test_route_falls_back_to_qps_when_match_below_threshold():
    """
    When the longest prefix match is shorter than prefix_min_match_length
    and engine_stats are unavailable, the request falls back to QPS-based
    routing and picks the engine with the lowest QPS.

    The prompt must still be inserted into the trie, attributed to the
    selected endpoint. otherwise a router that starts with an empty trie
    never seeds it (every request matches below the threshold), and prefix
    affinity never activates.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    request = Request(headers={})
    request_json = {"prompt": "some prompt text"}

    router = PrefixAwareRouter(prefix_min_match_length=4096)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (
        0,
        {"http://engine1.com"},
    )
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )

    assert url == "http://engine2.com"

    fake_hashtrie.insert.assert_awaited_once_with(
        "some prompt text", "http://engine2.com"
    )


@pytest.mark.asyncio
async def test_below_threshold_prefers_least_inflight_over_stale_qps():
    """
    Starvation / positive-feedback case (#1073).

    Backend B is mid long-running session: windowed QPS looks low (few
    completions) while instantaneous in-flight is high. a new session's
    first request matches below the threshold. using QPS would pick B and
    the trie insert would latch that bad pick for the session. least-
    inflight must prefer the idle backend A instead.
    """

    endpoints = [
        EndpointInfo(url="http://engine-a.com"),
        EndpointInfo(url="http://engine-b.com"),
    ]
    # stale qps: b looks "least busy" because long requests rarely complete
    request_stats = {
        "http://engine-a.com": RequestStats(qps=8.0),
        "http://engine-b.com": RequestStats(qps=1.0),
    }
    # instantaneous load: b is saturated, a is idle
    engine_stats = {
        "http://engine-a.com": EngineStats(
            num_running_requests=0, num_queuing_requests=0
        ),
        "http://engine-b.com": EngineStats(
            num_running_requests=4, num_queuing_requests=4
        ),
    }
    request = Request(headers={})
    request_json = {"prompt": "new session prompt"}

    router = PrefixAwareRouter(prefix_min_match_length=4096)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (0, set())
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, engine_stats, request_stats, request, request_json
    )

    assert url == "http://engine-a.com"
    fake_hashtrie.insert.assert_awaited_once_with(
        "new session prompt", "http://engine-a.com"
    )


@pytest.mark.asyncio
async def test_below_threshold_falls_back_to_qps_when_engine_stats_incomplete():
    """
    If any endpoint is missing from engine_stats (cold scrape / scrape
    failure), least-inflight returns None and the branch falls back to QPS.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    # engine2 missing from scrape
    engine_stats = {
        "http://engine1.com": EngineStats(
            num_running_requests=9, num_queuing_requests=0
        ),
    }
    request = Request(headers={})
    request_json = {"prompt": "some prompt text"}

    router = PrefixAwareRouter(prefix_min_match_length=4096)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (0, set())
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, engine_stats, request_stats, request, request_json
    )

    assert url == "http://engine2.com"
    fake_hashtrie.insert.assert_awaited_once_with(
        "some prompt text", "http://engine2.com"
    )


@pytest.mark.asyncio
async def test_below_threshold_near_tied_inflight_spreads_burst():
    """
    When several backends are within +1 of the minimum in-flight load,
    selection is random among them so a burst inside one scrape window
    does not dogpile a single url.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
        EndpointInfo(url="http://engine3.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(qps=1),
        "http://engine2.com": RequestStats(qps=1),
        "http://engine3.com": RequestStats(qps=1),
    }
    engine_stats = {
        "http://engine1.com": EngineStats(
            num_running_requests=2, num_queuing_requests=0
        ),
        "http://engine2.com": EngineStats(
            num_running_requests=2, num_queuing_requests=1
        ),
        "http://engine3.com": EngineStats(
            num_running_requests=5, num_queuing_requests=0
        ),
    }
    request = Request(headers={})

    router = PrefixAwareRouter(prefix_min_match_length=4096)
    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (0, set())
    router.hashtrie = fake_hashtrie

    counts: Counter = Counter()
    # deterministic but covers both near-tied urls across many draws
    with patch(
        "vllm_router.routers.routing_logic.random.choice", side_effect=lambda xs: xs[0]
    ):
        url = await router.route_request(
            endpoints,
            engine_stats,
            request_stats,
            request,
            {"prompt": "burst-0"},
        )
        counts[url] += 1
    with patch(
        "vllm_router.routers.routing_logic.random.choice", side_effect=lambda xs: xs[-1]
    ):
        url = await router.route_request(
            endpoints,
            engine_stats,
            request_stats,
            request,
            {"prompt": "burst-1"},
        )
        counts[url] += 1

    assert set(counts) <= {"http://engine1.com", "http://engine2.com"}
    assert "http://engine3.com" not in counts
    assert len(set(counts)) == 2


@pytest.mark.asyncio
async def test_below_threshold_seeding_enables_later_pinning():
    """
    Regression test for the trie never seeding when
    prefix_min_match_length > 0.

    Uses the real HashTrie. the first request has no prefix match, so it is
    routed by the below-threshold fallback (qps here, no engine_stats) - but
    it must seed the trie. a follow-up request extending the same prompt
    then matches above the threshold and must pin to the endpoint that
    served the first request, even when qps stats would prefer the other
    endpoint.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request = Request(headers={})

    # 128 = one HashTrie chunk; the first chunk of both prompts is identical.
    router = PrefixAwareRouter(prefix_min_match_length=128)

    first_prompt = "x" * 128 + "y" * 72
    followup_prompt = first_prompt + "z" * 40

    # First request: cold trie, match below threshold -> QPS picks engine1.
    request_stats = {
        "http://engine1.com": RequestStats(qps=5),
        "http://engine2.com": RequestStats(qps=10),
    }
    url = await router.route_request(
        endpoints, None, request_stats, request, {"prompt": first_prompt}
    )
    assert url == "http://engine1.com"

    # Follow-up: shares the first 128-char chunk, so it matches at the
    # threshold and must pin to engine1 even though engine2 now has the
    # lower QPS.
    request_stats = {
        "http://engine1.com": RequestStats(qps=10),
        "http://engine2.com": RequestStats(qps=5),
    }
    url = await router.route_request(
        endpoints, None, request_stats, request, {"prompt": followup_prompt}
    )
    assert url == "http://engine1.com"


@pytest.mark.asyncio
async def test_least_inflight_seeding_pins_followup_away_from_busy_backend():
    """
    End-to-end with real HashTrie: below-threshold least-inflight seeds the
    idle backend; a follow-up above the threshold stays pinned there even
    though stale qps still points at the busy backend.
    """

    endpoints = [
        EndpointInfo(url="http://engine-a.com"),
        EndpointInfo(url="http://engine-b.com"),
    ]
    request = Request(headers={})
    router = PrefixAwareRouter(prefix_min_match_length=128)

    first_prompt = "a" * 128 + "b" * 72
    followup_prompt = first_prompt + "c" * 40

    request_stats = {
        "http://engine-a.com": RequestStats(qps=9.0),
        "http://engine-b.com": RequestStats(qps=0.5),
    }
    engine_stats = {
        "http://engine-a.com": EngineStats(
            num_running_requests=0, num_queuing_requests=0
        ),
        "http://engine-b.com": EngineStats(
            num_running_requests=6, num_queuing_requests=2
        ),
    }

    url = await router.route_request(
        endpoints, engine_stats, request_stats, request, {"prompt": first_prompt}
    )
    assert url == "http://engine-a.com"

    url = await router.route_request(
        endpoints, engine_stats, request_stats, request, {"prompt": followup_prompt}
    )
    assert url == "http://engine-a.com"


@pytest.mark.asyncio
async def test_route_uses_matched_endpoint_when_match_above_threshold():
    """
    When the longest prefix match is no shorter than prefix_min_match_length,
    the request should use the matched endpoint.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {}
    request = Request(headers={})
    request_json = {"prompt": "some prompt text"}

    router = PrefixAwareRouter(prefix_min_match_length=128)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (
        4096,
        {"http://engine1.com"},
    )
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )

    assert url == "http://engine1.com"

    fake_hashtrie.insert.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_threshold_zero_preserves_original_behavior():
    """
    When --prefix-min-match-length is not provided, prefix_min_match_length
    defaults to 0. even when there is no prefix match at all (match_length 0),
    the request still uses the matched endpoint instead of falling back,
    preserving the original behavior before this change.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {}
    request = Request(headers={})
    request_json = {"prompt": "some prompt text"}

    router = PrefixAwareRouter()

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (
        0,
        {"http://engine1.com"},
    )
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )

    assert url == "http://engine1.com"

    fake_hashtrie.insert.assert_awaited_once()
