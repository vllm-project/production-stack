from typing import Any, Dict
from unittest.mock import AsyncMock

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


class Request:
    def __init__(self, headers: Dict[str, str], body: Dict[str, Any] = None):
        self.headers = headers
        self.body = body


@pytest.mark.asyncio
async def test_route_falls_back_to_qps_when_match_below_threshold():
    """
    When the longest prefix match is shorter than prefix_min_match_length,
    the request should NOT use the matched endpoint. It should fall back to
    QPS-based routing and pick the engine with the lowest QPS.

    The prompt must still be inserted into the trie, attributed to the
    QPS-selected endpoint. Otherwise a router that starts with an empty trie
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
async def test_below_threshold_seeding_enables_later_pinning():
    """
    Regression test for the trie never seeding when
    prefix_min_match_length > 0.

    Uses the real HashTrie. The first request has no prefix match, so it is
    routed by QPS — but it must seed the trie. A follow-up request extending
    the same prompt then matches above the threshold and must pin to the
    endpoint that served the first request, even when QPS stats would prefer
    the other endpoint.
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
    defaults to 0. Even when there is no prefix match at all (match_length 0),
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
