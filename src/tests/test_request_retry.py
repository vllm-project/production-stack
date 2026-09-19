"""End-to-end behaviour of the retry policy inside ``route_general_request``.

``process_request`` reports a backend error status by *yielding* it, not by
raising, so every stand-in here does the same. A stand-in that raises
``HTTPException`` for a backend status would not exercise the retry path at
all and would pass regardless of whether retrying works.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.routers.routing_logic import RoundRobinRouter
from vllm_router.services.request_service import request as request_module
from vllm_router.services.request_service import retry as retry_module
from vllm_router.services.request_service.retry import RetryConfig
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["test-model"]
        self.sleep = sleep
        self.Id = Id


ENDPOINTS = [EndpointInfo(url="http://engine1"), EndpointInfo(url="http://engine2")]

MOCK_HEADERS = MagicMock()
MOCK_HEADERS.items.return_value = [("content-type", "text/event-stream")]

# Keep the backoff out of the test clock; the maths is covered in
# test_retry_config.py.
FAST = {"initial_backoff_ms": 1}


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


def _make_request(endpoints=ENDPOINTS, retry_config=None):
    """Build a request whose app state is wired for routing."""
    router = RoundRobinRouter()

    sd = MagicMock()
    sd.get_endpoint_info.return_value = list(endpoints)
    sd.aliases = None
    sd.has_ever_seen_model.return_value = True

    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None
    state.external_provider_registry = None
    state.retry_config = retry_config or RetryConfig()

    req = MagicMock()
    req.headers = {"content-type": "application/json"}
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/chat/completions"
    req.app.state = state

    async def body():
        return json.dumps({"model": "test-model", "stream": False}).encode()

    req.body = body
    return req, router, sd


@pytest.fixture
def setup():
    """A request against two engines, with retries disabled by default."""
    req, router, sd = _make_request()
    patches = [
        patch.object(request_module, "get_service_discovery", return_value=sd),
        patch.object(
            request_module, "is_request_rewriter_initialized", return_value=False
        ),
    ]
    for p in patches:
        p.start()
    yield req, router
    for p in patches:
        p.stop()


def _responds(status, calls, ok_after=None):
    """A ``process_request`` stand-in that yields ``status`` then a body.

    With ``ok_after`` the first ``ok_after`` calls yield ``status`` and the
    rest yield 200.
    """

    async def _impl(r, body, server_url, *a, **kw):
        calls.append(server_url)
        code = status if ok_after is None or len(calls) <= ok_after else 200
        yield MOCK_HEADERS, code
        yield b"body"

    return _impl


def _fails(exc, calls, ok_after=None):
    """A stand-in that raises ``exc`` as a transport failure."""

    async def _impl(r, body, server_url, *a, **kw):
        calls.append(server_url)
        if ok_after is None or len(calls) <= ok_after:
            raise exc
        yield MOCK_HEADERS, 200
        yield b"body"

    return _impl


async def _route(req):
    return await request_module.route_general_request(
        req, "/v1/chat/completions", MagicMock()
    )


def _patch_process(impl):
    return patch.object(request_module, "process_request", side_effect=impl)


def _patch_discovery(sd):
    return (
        patch.object(request_module, "get_service_discovery", return_value=sd),
        patch.object(
            request_module, "is_request_rewriter_initialized", return_value=False
        ),
    )


def _patch_sleep(recorder):
    async def fake_sleep(delay):
        recorder.append(delay)

    return patch.object(retry_module.asyncio, "sleep", fake_sleep)


# Default configuration: exactly one attempt.


@pytest.mark.asyncio
async def test_successful_request_is_attempted_once(setup):
    req, _ = setup
    calls = []

    with _patch_process(_responds(200, calls)):
        resp = await _route(req)

    assert resp.status_code == 200
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_retryable_status_is_not_retried_by_default(setup):
    """Retries are opt-in, so the default must preserve fail-fast behaviour."""
    req, _ = setup
    calls = []

    with _patch_process(_responds(503, calls)):
        resp = await _route(req)

    assert resp.status_code == 503
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_transport_failure_is_not_retried_by_default(setup):
    req, _ = setup
    calls = []

    with _patch_process(_fails(ConnectionError("down"), calls)):
        with pytest.raises(ConnectionError):
            await _route(req)

    assert len(calls) == 1


# Transport failures: exclude the engine, reroute immediately.


@pytest.mark.asyncio
async def test_transport_failure_reroutes_to_another_engine(setup):
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=3, **FAST)
    calls = []

    with _patch_process(_fails(ConnectionError("down"), calls, ok_after=1)):
        resp = await _route(req)

    assert resp.status_code == 200
    assert calls[0] != calls[1], "a failed engine must not be retried immediately"


@pytest.mark.asyncio
async def test_transport_failure_reroute_is_not_delayed(setup):
    """A dead engine must fail over at once, not wait out a retry backoff."""
    req, _ = setup
    req.app.state.retry_config = RetryConfig(
        max_attempts=5, initial_backoff_ms=10_000, backoff_multiplier=2.0
    )
    calls, slept = [], []

    with (
        _patch_process(_fails(ConnectionError("down"), calls, ok_after=1)),
        _patch_sleep(slept),
    ):
        resp = await _route(req)

    assert resp.status_code == 200
    assert slept == [], "another engine was available, so no backoff is due"


@pytest.mark.asyncio
async def test_error_is_raised_once_every_engine_failed(setup):
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=2, **FAST)
    calls = []

    with _patch_process(_fails(ConnectionError("down"), calls)):
        with pytest.raises(ConnectionError):
            await _route(req)

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_budget_is_not_spent_on_already_excluded_engines(setup):
    """More attempts than engines must not loop pointlessly."""
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=10, **FAST)
    calls = []

    with _patch_process(_fails(ConnectionError("down"), calls)):
        with pytest.raises(ConnectionError):
            await _route(req)

    # Two engines, ten attempts: the pool is retried, not spun on.
    assert len(calls) == 10
    assert set(calls) == {"http://engine1", "http://engine2"}


@pytest.mark.asyncio
async def test_single_engine_transport_failure_is_retried():
    """The only engine is retried after a backoff rather than abandoned."""
    req, _, sd = _make_request(
        endpoints=[EndpointInfo(url="http://engine1")],
        retry_config=RetryConfig(max_attempts=3, **FAST),
    )
    calls = []

    discovery, rewriter = _patch_discovery(sd)
    with (
        discovery,
        rewriter,
        _patch_process(_fails(ConnectionError("down"), calls, ok_after=1)),
    ):
        resp = await _route(req)

    assert resp.status_code == 200
    assert calls == ["http://engine1", "http://engine1"]


# Transient statuses: keep the engine, back off, re-issue.


@pytest.mark.asyncio
async def test_retryable_status_is_retried(setup):
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=4, **FAST)
    calls = []

    with _patch_process(_responds(503, calls, ok_after=1)):
        resp = await _route(req)

    assert resp.status_code == 200
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retryable_status_keeps_the_engine_eligible():
    """A busy engine is not broken, so a single-engine pool still retries."""
    req, _, sd = _make_request(
        endpoints=[EndpointInfo(url="http://engine1")],
        retry_config=RetryConfig(max_attempts=3, **FAST),
    )
    calls = []

    discovery, rewriter = _patch_discovery(sd)
    with (
        discovery,
        rewriter,
        _patch_process(_responds(503, calls, ok_after=1)),
    ):
        resp = await _route(req)

    assert resp.status_code == 200
    assert calls == ["http://engine1", "http://engine1"]


@pytest.mark.asyncio
async def test_backend_response_passes_through_when_budget_is_spent(setup):
    """The client gets the backend's own status, not a synthesised error."""
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=3, **FAST)
    calls = []

    with _patch_process(_responds(503, calls)):
        resp = await _route(req)

    assert resp.status_code == 503
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_non_retryable_status_is_returned_immediately(setup):
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=5, **FAST)
    calls = []

    with _patch_process(_responds(400, calls)):
        resp = await _route(req)

    assert resp.status_code == 400
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_discarded_attempt_closes_the_upstream_generator(setup):
    """A discarded response must be closed so the connection is released."""
    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=3, **FAST)
    calls, closed = [], []

    async def impl(r, body, server_url, *a, **kw):
        calls.append(server_url)
        try:
            yield MOCK_HEADERS, 503 if len(calls) == 1 else 200
            yield b"body"
        except GeneratorExit:
            closed.append(server_url)
            raise

    with _patch_process(impl):
        resp = await _route(req)

    assert resp.status_code == 200
    assert len(closed) == 1


@pytest.mark.asyncio
async def test_backoff_grows_across_successive_retries(setup):
    req, _ = setup
    req.app.state.retry_config = RetryConfig(
        max_attempts=4,
        initial_backoff_ms=100,
        backoff_multiplier=2.0,
        jitter_factor=0.0,
    )
    calls, slept = [], []

    with _patch_process(_responds(503, calls)), _patch_sleep(slept):
        await _route(req)

    assert slept == [0.1, 0.2, 0.4]


# Client errors are never retried.


@pytest.mark.asyncio
async def test_http_exception_is_not_retried(setup):
    """A malformed request is the caller's fault; retrying cannot help."""
    from fastapi import HTTPException

    req, _ = setup
    req.app.state.retry_config = RetryConfig(max_attempts=5, **FAST)
    calls = []

    async def impl(*a, **kw):
        calls.append(1)
        raise HTTPException(status_code=400, detail="bad request")
        yield

    with _patch_process(impl):
        with pytest.raises(HTTPException):
            await _route(req)

    assert len(calls) == 1
