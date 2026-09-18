import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.routers.routing_logic import RoundRobinRouter
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


def make_request(disconnected):
    """Build a request whose client is either connected or already gone."""
    router = RoundRobinRouter()
    router.max_instance_failover_reroute_attempts = 1

    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None
    state.external_provider_registry = None

    req = MagicMock()
    req.headers = {"content-type": "application/json"}
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/chat/completions"
    req.app.state = state

    async def body():
        return json.dumps({"model": "test-model", "stream": False}).encode()

    async def receive():
        if disconnected:
            return {"type": "http.disconnect"}
        await asyncio.Event().wait()

    req.body = body
    req.receive = receive
    return req


@pytest.fixture
def patched_discovery():
    sd = MagicMock()
    sd.get_endpoint_info.return_value = ENDPOINTS
    sd.aliases = None
    sd.has_ever_seen_model.return_value = True

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
    yield sd
    for p in patches:
        p.stop()


@pytest.mark.asyncio
async def test_disconnect_before_headers_aborts_backend_request(patched_discovery):
    """A client that gives up while the engine is still generating must not be
    waited out: the backend request has to be torn down instead."""
    from vllm_router.services.request_service.request import route_general_request

    req = make_request(disconnected=True)
    torn_down = []

    async def never_responds(*a, **kw):
        try:
            await asyncio.Event().wait()
            yield MagicMock(), 200
        finally:
            torn_down.append(True)

    with patch(
        "vllm_router.services.request_service.request.process_request",
        side_effect=never_responds,
    ) as mock:
        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 499
    assert torn_down == [True]
    # A dead client is not an engine failure, so no other engine is tried.
    assert mock.call_count == 1


@pytest.mark.asyncio
async def test_connected_client_still_gets_the_response(patched_discovery):
    """The disconnect listener must not interfere with the normal path."""
    from vllm_router.services.request_service.request import route_general_request

    req = make_request(disconnected=False)
    headers = MagicMock()
    headers.items.return_value = [("content-type", "text/event-stream")]

    async def ok(*a, **kw):
        yield headers, 200
        yield b"done"

    with patch(
        "vllm_router.services.request_service.request.process_request", side_effect=ok
    ):
        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200


class FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_any(self):
        for chunk in self._chunks:
            yield chunk


class FakeBackendResponse:
    def __init__(self, chunks):
        self.status = 200
        self.headers = {"content-type": "text/event-stream"}
        self.content = FakeContent(chunks)


class FakeRequestContext:
    """Stands in for the aiohttp request context manager."""

    def __init__(self, response, released):
        self._response = response
        self._released = released

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        self._released.append(True)
        return False


def make_process_request_args(released, chunks):
    state = MagicMock()
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None
    state.request_stats_monitor = MagicMock()
    state.aiohttp_client_wrapper.return_value.request = (
        lambda **kwargs: FakeRequestContext(FakeBackendResponse(chunks), released)
    )

    req = MagicMock()
    req.headers = {"content-type": "application/json"}
    req.method = "POST"
    req.app.state = state
    return req, state.request_stats_monitor


@pytest.mark.asyncio
async def test_abandoned_stream_is_marked_complete():
    """An engine must stop being counted as busy once the stream is abandoned,
    otherwise the load it reports to the routing logic never recovers."""
    from vllm_router.services.request_service.request import process_request

    released = []
    req, monitor = make_process_request_args(released, [b"a", b"b", b"c"])
    body = json.dumps({"model": "test-model", "stream": True}).encode()

    gen = process_request(req, body, "http://engine1", "req-1", "/v1/completions", None)
    await anext(gen)  # headers and status
    await anext(gen)  # first chunk
    await gen.aclose()  # the client went away

    monitor.on_new_request.assert_called_once()
    monitor.on_request_complete.assert_called_once()
    assert released == [True]


@pytest.mark.asyncio
async def test_fully_consumed_stream_is_marked_complete_once():
    from vllm_router.services.request_service.request import process_request

    released = []
    req, monitor = make_process_request_args(released, [b"a", b"b"])
    body = json.dumps({"model": "test-model", "stream": True}).encode()

    gen = process_request(req, body, "http://engine1", "req-1", "/v1/completions", None)
    chunks = [chunk async for chunk in gen]

    assert chunks[1:] == [b"a", b"b"]
    monitor.on_request_complete.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_and_wait_swallows_only_its_own_cancellation():
    """Cancelling `task` alone must not raise out of `_cancel_and_wait`."""
    from vllm_router.services.request_service.request import _cancel_and_wait

    task = asyncio.ensure_future(asyncio.sleep(1000))
    await _cancel_and_wait(task)  # must not raise
    assert task.cancelled()


@pytest.mark.asyncio
async def test_cancel_and_wait_reraises_an_unrelated_caller_cancellation():
    """A caller cancelled independently while inside `_cancel_and_wait` must see
    that cancellation, not have it absorbed by the cancellation of `task`.

    `task.cancelled()` can't tell the two apart, since cancelling the caller
    while it awaits `task` also cancels `task` via `_fut_waiter` propagation --
    this is what the `cancelling()`-based check exists to fix.
    """
    from vllm_router.services.request_service.request import _cancel_and_wait

    task = asyncio.ensure_future(asyncio.sleep(1000))
    outcome = {}

    async def caller():
        try:
            await _cancel_and_wait(task)
            outcome["raised"] = False
        except asyncio.CancelledError:
            outcome["raised"] = True

    caller_task = asyncio.ensure_future(caller())
    await asyncio.sleep(0)
    await asyncio.sleep(0)  # let caller_task reach `await task` inside _cancel_and_wait
    caller_task.cancel()  # aimed at the caller, not at `task`
    await asyncio.wait([caller_task])

    assert outcome["raised"] is True
