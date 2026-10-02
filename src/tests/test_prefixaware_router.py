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
    def __init__(
        self,
        qps: float = 0.0,
        in_prefill_requests: int = 0,
        in_decoding_requests: int = 0,
    ):
        self.qps = qps
        self.in_prefill_requests = in_prefill_requests
        self.in_decoding_requests = in_decoding_requests


class Request:
    def __init__(self, headers: Dict[str, str], body: Dict[str, Any] = None):
        self.headers = headers
        self.body = body


@pytest.mark.asyncio
async def test_below_threshold_prefers_least_inflight_over_stale_qps():
    """
    Starvation / positive-feedback case (#1073).

    Backend B is mid long-running session: windowed QPS looks low (few
    completions) while instantaneous in-flight is high. a new session's
    first request matches below the threshold. using QPS would pick B and
    the trie insert would latch that bad pick for the session. least-
    inflight via request_stats must prefer the idle backend A instead.
    """

    endpoints = [
        EndpointInfo(url="http://engine-a.com"),
        EndpointInfo(url="http://engine-b.com"),
    ]
    # stale qps: b looks "least busy" because long requests rarely complete;
    # request_stats in-flight: b is saturated, a is idle
    request_stats = {
        "http://engine-a.com": RequestStats(
            qps=8.0, in_prefill_requests=0, in_decoding_requests=0
        ),
        "http://engine-b.com": RequestStats(
            qps=1.0, in_prefill_requests=4, in_decoding_requests=4
        ),
    }
    request = Request(headers={})
    request_json = {"prompt": "new session prompt"}

    router = PrefixAwareRouter(prefix_min_match_length=4096)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (0, set())
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )

    assert url == "http://engine-a.com"
    fake_hashtrie.insert.assert_awaited_once_with(
        "new session prompt", "http://engine-a.com"
    )


@pytest.mark.asyncio
async def test_below_threshold_missing_request_stats_entry_is_load_zero():
    """
    A URL absent from request_stats has load 0 (idle / never served), so it
    wins over a known busy backend. does not fall back to QPS.
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    # engine2 missing => load 0. stale qps would prefer engine1 if we mixed.
    request_stats = {
        "http://engine1.com": RequestStats(
            qps=1.0, in_prefill_requests=9, in_decoding_requests=0
        ),
    }
    request = Request(headers={})
    request_json = {"prompt": "some prompt text"}

    router = PrefixAwareRouter(prefix_min_match_length=4096)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (0, set())
    router.hashtrie = fake_hashtrie

    url = await router.route_request(
        endpoints, None, request_stats, request, request_json
    )

    assert url == "http://engine2.com"
    fake_hashtrie.insert.assert_awaited_once_with(
        "some prompt text", "http://engine2.com"
    )


@pytest.mark.asyncio
async def test_below_threshold_exact_min_ties_spread_and_exclude_near_min():
    """
    Random among endpoints at the exact minimum load only. a backend at
    min+1 is not in the candidate set (no +1 near-tie band).
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
        EndpointInfo(url="http://engine3.com"),
    ]
    # loads: 2, 2, 3. exact-min candidates are engine1 and engine2 only.
    request_stats = {
        "http://engine1.com": RequestStats(
            qps=1, in_prefill_requests=2, in_decoding_requests=0
        ),
        "http://engine2.com": RequestStats(
            qps=1, in_prefill_requests=1, in_decoding_requests=1
        ),
        "http://engine3.com": RequestStats(
            qps=1, in_prefill_requests=3, in_decoding_requests=0
        ),
    }
    request = Request(headers={})

    router = PrefixAwareRouter(prefix_min_match_length=4096)
    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (0, set())
    router.hashtrie = fake_hashtrie

    counts: Counter = Counter()
    with patch(
        "vllm_router.routers.routing_logic.random.choice", side_effect=lambda xs: xs[0]
    ):
        url = await router.route_request(
            endpoints,
            None,
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
            None,
            request_stats,
            request,
            {"prompt": "burst-1"},
        )
        counts[url] += 1

    assert set(counts) <= {"http://engine1.com", "http://engine2.com"}
    assert "http://engine3.com" not in counts
    assert len(set(counts)) == 2


@pytest.mark.asyncio
async def test_below_threshold_cold_all_zero_seeds_trie():
    """
    Empty / all-zero request_stats: every endpoint has load 0, so selection
    is random among all, and the chosen url is still inserted into the trie
    (#990 seeding).
    """

    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats: Dict[str, RequestStats] = {}
    request = Request(headers={})
    request_json = {"prompt": "some prompt text"}

    router = PrefixAwareRouter(prefix_min_match_length=4096)

    fake_hashtrie = AsyncMock()
    fake_hashtrie.longest_prefix_match.return_value = (
        0,
        {"http://engine1.com"},
    )
    router.hashtrie = fake_hashtrie

    with patch(
        "vllm_router.routers.routing_logic.random.choice",
        side_effect=lambda xs: "http://engine2.com",
    ):
        url = await router.route_request(
            endpoints, None, request_stats, request, request_json
        )

    assert url == "http://engine2.com"
    fake_hashtrie.insert.assert_awaited_once_with(
        "some prompt text", "http://engine2.com"
    )


@pytest.mark.asyncio
async def test_below_threshold_seeding_enables_later_pinning():
    """
    Regression test for the trie never seeding when
    prefix_min_match_length > 0.

    Uses the real HashTrie. the first request has no prefix match, so it is
    routed by least-inflight via request_stats - but it must seed the trie.
    a follow-up request extending the same prompt then matches above the
    threshold and must pin to the endpoint that served the first request,
    even when request_stats would prefer the other endpoint.
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

    # First request: cold trie, match below threshold -> least-inflight
    # picks engine1 (unique min load).
    request_stats = {
        "http://engine1.com": RequestStats(
            qps=5, in_prefill_requests=0, in_decoding_requests=0
        ),
        "http://engine2.com": RequestStats(
            qps=10, in_prefill_requests=3, in_decoding_requests=0
        ),
    }
    url = await router.route_request(
        endpoints, None, request_stats, request, {"prompt": first_prompt}
    )
    assert url == "http://engine1.com"

    # Follow-up: shares the first 128-char chunk, so it matches at the
    # threshold and must pin to engine1 even though engine2 now has the
    # lower in-flight load.
    request_stats = {
        "http://engine1.com": RequestStats(
            qps=10, in_prefill_requests=5, in_decoding_requests=0
        ),
        "http://engine2.com": RequestStats(
            qps=5, in_prefill_requests=0, in_decoding_requests=0
        ),
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
        "http://engine-a.com": RequestStats(
            qps=9.0, in_prefill_requests=0, in_decoding_requests=0
        ),
        "http://engine-b.com": RequestStats(
            qps=0.5, in_prefill_requests=6, in_decoding_requests=2
        ),
    }

    url = await router.route_request(
        endpoints, None, request_stats, request, {"prompt": first_prompt}
    )
    assert url == "http://engine-a.com"

    url = await router.route_request(
        endpoints, None, request_stats, request, {"prompt": followup_prompt}
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
