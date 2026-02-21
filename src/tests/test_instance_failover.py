import json
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.routers.routing_logic import (
    RoundRobinRouter,
    RoutingLogic,
    initialize_routing_logic,
)
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["test-model"]
        self.sleep = sleep
        self.Id = Id


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


ENDPOINTS = [EndpointInfo(url="http://engine1"), EndpointInfo(url="http://engine2")]

MOCK_HEADERS = MagicMock()
MOCK_HEADERS.items.return_value = [("content-type", "text/event-stream")]


@pytest.fixture
def setup():
    """Yield (request, background_tasks) with all dependencies patched."""
    router = RoundRobinRouter()
    router.max_instance_failover_reroute_attempts = 1

    sd = MagicMock()
    sd.get_endpoint_info.return_value = ENDPOINTS
    sd.aliases = None
    sd.has_ever_seen_model.return_value = True

    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None

    req = MagicMock()
    req.headers = {"content-type": "application/json"}
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/chat/completions"
    req.app.state = state

    async def body():
        return json.dumps({"model": "test-model", "stream": False}).encode()

    req.body = body

    patches = [
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=sd,
        ),
        patch(
            "vllm_router.services.request_service.request.is_request_rewriter_initialized",
            return_value=False,
        ),
    ]
    for p in patches:
        p.start()
    yield req, router
    for p in patches:
        p.stop()


def test_initialize_sets_failover_attempts():
    assert (
        initialize_routing_logic(
            RoutingLogic.ROUND_ROBIN
        ).max_instance_failover_reroute_attempts
        == 0
    )
    assert (
        initialize_routing_logic(
            RoutingLogic.ROUND_ROBIN, max_instance_failover_reroute_attempts=3
        ).max_instance_failover_reroute_attempts
        == 3
    )


@pytest.mark.asyncio
async def test_no_retry_on_success(setup):
    req, router = setup

    async def ok(*a, **kw):
        yield MOCK_HEADERS, 200
        yield b"done"

    with patch(
        "vllm_router.services.request_service.request.process_request", side_effect=ok
    ) as mock:
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200
    assert mock.call_count == 1


@pytest.mark.asyncio
async def test_retries_on_failure_with_different_url(setup):
    req, router = setup
    urls_called = []

    async def fail_then_ok(r, body, server_url, *a, **kw):
        urls_called.append(server_url)
        if len(urls_called) == 1:
            raise ConnectionError("down")
        yield MOCK_HEADERS, 200
        yield b"done"

    with patch(
        "vllm_router.services.request_service.request.process_request",
        side_effect=fail_then_ok,
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200
    assert len(urls_called) == 2
    assert urls_called[0] != urls_called[1]


@pytest.mark.asyncio
async def test_raises_after_all_attempts_exhausted(setup):
    req, router = setup

    async def fail(*a, **kw):
        raise ConnectionError("down")
        yield

    with patch(
        "vllm_router.services.request_service.request.process_request", side_effect=fail
    ):
        from vllm_router.services.request_service.request import route_general_request

        with pytest.raises(ConnectionError):
            await route_general_request(req, "/v1/chat/completions", MagicMock())


@pytest.mark.asyncio
async def test_no_retry_when_disabled(setup):
    req, router = setup
    router.max_instance_failover_reroute_attempts = 0
    call_count = 0

    async def fail(*a, **kw):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("down")
        yield

    with patch(
        "vllm_router.services.request_service.request.process_request", side_effect=fail
    ):
        from vllm_router.services.request_service.request import route_general_request

        with pytest.raises(ConnectionError):
            await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert call_count == 1


@pytest.mark.asyncio
async def test_breaks_when_no_remaining_endpoints(setup):
    req, router = setup
    router.max_instance_failover_reroute_attempts = 5  # more retries than endpoints

    async def fail(*a, **kw):
        raise ConnectionError("down")
        yield

    with patch(
        "vllm_router.services.request_service.request.process_request", side_effect=fail
    ):
        from vllm_router.services.request_service.request import route_general_request

        with pytest.raises(ConnectionError):
            await route_general_request(req, "/v1/chat/completions", MagicMock())


@pytest.mark.asyncio
async def test_http_exception_not_retried(setup):
    from fastapi import HTTPException

    req, router = setup
    router.max_instance_failover_reroute_attempts = 3
    call_count = 0

    async def fail(*a, **kw):
        nonlocal call_count
        call_count += 1
        raise HTTPException(status_code=400, detail="bad request")
        yield

    with patch(
        "vllm_router.services.request_service.request.process_request", side_effect=fail
    ):
        from vllm_router.services.request_service.request import route_general_request

        with pytest.raises(HTTPException):
            await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert call_count == 1
