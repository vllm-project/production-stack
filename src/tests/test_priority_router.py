from typing import Any, Dict

import pytest

from vllm_router.routers.routing_logic import (
    PriorityRouter,
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
    def __init__(self, in_prefill_requests: int = 0, in_decoding_requests: int = 0):
        self.in_prefill_requests = in_prefill_requests
        self.in_decoding_requests = in_decoding_requests


class Request:
    def __init__(self, headers: Dict[str, str] = None):
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_priority_extraction_precedence_header_over_body():
    router = PriorityRouter(priority_default=0)
    request = Request(headers={"x-request-priority": "-5"})
    request_json: Dict[str, Any] = {"priority": 3}

    assert router.extract_priority(request, request_json) == -5


@pytest.mark.asyncio
async def test_priority_extraction_precedence_body_over_default():
    router = PriorityRouter(priority_default=0)
    request = Request(headers={})
    request_json: Dict[str, Any] = {"priority": 3}

    assert router.extract_priority(request, request_json) == 3


@pytest.mark.asyncio
async def test_priority_extraction_falls_back_to_default():
    router = PriorityRouter(priority_default=7)
    request = Request(headers={})
    request_json: Dict[str, Any] = {}

    assert router.extract_priority(request, request_json) == 7


@pytest.mark.asyncio
async def test_malformed_priority_values_fall_back():
    router = PriorityRouter(priority_default=7)
    request = Request(headers={"x-request-priority": "not-an-int"})
    request_json: Dict[str, Any] = {"priority": "also-not-an-int"}

    assert router.extract_priority(request, request_json) == 7


@pytest.mark.asyncio
async def test_high_priority_request_selects_least_loaded_engine():
    router = PriorityRouter(priority_default=0, priority_threshold=0)
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(in_prefill_requests=5, in_decoding_requests=5),
        "http://engine2.com": RequestStats(in_prefill_requests=1, in_decoding_requests=0),
    }
    request = Request(headers={"x-request-priority": "-1"})
    request_json: Dict[str, Any] = {}

    url = await router.route_request(endpoints, None, request_stats, request, request_json)

    assert url == "http://engine2.com"
    # Priority must be injected back into the forwarded body.
    assert request_json["priority"] == -1


@pytest.mark.asyncio
async def test_default_priority_is_not_treated_as_high_priority():
    """
    Exclusive threshold boundary (Option A): a request carrying exactly the
    default/threshold priority must NOT be classified as high-priority, so
    priority routing stays opt-in with zero extra configuration.
    """
    router = PriorityRouter(priority_default=0, priority_threshold=0)
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats = {
        "http://engine1.com": RequestStats(in_prefill_requests=5, in_decoding_requests=5),
        "http://engine2.com": RequestStats(in_prefill_requests=0, in_decoding_requests=0),
    }
    request = Request(headers={})
    request_json: Dict[str, Any] = {}

    # No priority given -> resolves to default (0), which is not < threshold
    # (0), so it must round-robin rather than jump straight to engine2.
    url = await router.route_request(endpoints, None, request_stats, request, request_json)

    assert url == "http://engine1.com"


@pytest.mark.asyncio
async def test_round_robin_candidates_include_least_loaded_engine():
    """
    Round-robin must consider every healthy engine, including the
    least-loaded one, so capacity is never left idle.
    """
    router = PriorityRouter(priority_default=0, priority_threshold=0)
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request_stats: Dict[str, RequestStats] = {}
    request = Request(headers={})

    seen = set()
    for _ in range(4):
        url = await router.route_request(
            endpoints, None, request_stats, request, {}
        )
        seen.add(url)

    assert seen == {"http://engine1.com", "http://engine2.com"}


@pytest.mark.asyncio
async def test_round_robin_fallback_when_no_stats_available():
    """
    Cold start: RequestStatsMonitor has no data for an engine yet, so it
    should be treated as zero load and routing should not error out.
    """
    router = PriorityRouter(priority_default=0, priority_threshold=1)
    endpoints = [
        EndpointInfo(url="http://engine1.com"),
        EndpointInfo(url="http://engine2.com"),
    ]
    request = Request(headers={"x-request-priority": "0"})

    url = await router.route_request(endpoints, None, {}, request, {})

    assert url in {"http://engine1.com", "http://engine2.com"}


@pytest.mark.asyncio
async def test_empty_endpoint_list_raises_value_error():
    router = PriorityRouter()
    request = Request(headers={})

    with pytest.raises(ValueError):
        await router.route_request([], None, {}, request, {})


@pytest.mark.asyncio
async def test_priority_threshold_defaults_to_priority_default():
    """
    When --priority-threshold is not provided, it should default to the
    value of --priority-default.
    """
    router = PriorityRouter(priority_default=5)

    assert router.priority_threshold == 5
