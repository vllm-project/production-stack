"""Client disconnects reach the engine.

A real uvicorn router and a real aiohttp fake engine: when the client leaves,
the router must close its upstream request so vLLM aborts the generation.
Non-streaming engines send headers only once generation finishes, so the
disconnect has to be noticed while the router still waits for them (#634).
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
import uvicorn
from aiohttp import web
from fastapi import FastAPI

from vllm_router.aiohttp_client import AiohttpClientWrapper
from vllm_router.routers.main_router import main_router
from vllm_router.routers.routing_logic import RoundRobinRouter
from vllm_router.services.request_service import request as request_module
from vllm_router.stats.request_stats import RequestStatsMonitor
from vllm_router.stats.request_stats import SingletonMeta as RequestStatsSingletonMeta
from vllm_router.utils import SingletonABCMeta

HOLD = 20.0  # engine generation time; every test must finish far sooner


@pytest.fixture(autouse=True)
def cleanup_singletons():
    RequestStatsSingletonMeta._instances.pop(RequestStatsMonitor, None)
    yield
    RequestStatsSingletonMeta._instances.pop(RequestStatsMonitor, None)
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


@pytest.fixture
async def engine():
    """Fake vLLM. Non-stream: headers after `hold` seconds. Stream: headers at
    once, then a chunk every 50 ms. Records when each upstream connection
    closes, keyed by X-Request-Id."""
    closed = {}
    release = asyncio.Event()

    def gone(request):
        return request.transport is None or request.transport.is_closing()

    async def chat(request):
        body = await request.json()
        request_id = request.headers["X-Request-Id"]
        if not body.get("stream"):
            deadline = time.monotonic() + body.get("hold", HOLD)
            while time.monotonic() < deadline and not release.is_set():
                if gone(request):
                    closed[request_id] = time.monotonic()
                    return web.Response(status=499)
                await asyncio.sleep(0.02)
            return web.json_response({"choices": [], "usage": {"completion_tokens": 1}})
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        try:
            while not release.is_set() and not gone(request):
                await response.write(b"data: {}\n\n")
                await asyncio.sleep(0.05)
        except ConnectionResetError:
            pass
        closed[request_id] = time.monotonic()
        return response

    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]

    yield SimpleNamespace(url=f"http://{host}:{port}", closed=closed)

    release.set()
    await runner.cleanup()


@pytest.fixture
async def router(engine):
    """The real router routes behind uvicorn, wired to the fake engine."""
    endpoint = SimpleNamespace(
        url=engine.url, model_names=["test-model"], sleep=False, Id=None
    )
    discovery = MagicMock()
    discovery.get_endpoint_info.return_value = [endpoint]
    discovery.aliases = None
    discovery.has_ever_seen_model.return_value = True

    routing = RoundRobinRouter()
    routing.max_instance_failover_reroute_attempts = 0
    client = AiohttpClientWrapper()
    client.start()

    app = FastAPI()
    app.include_router(main_router)
    app.state.router = routing
    app.state.engine_stats_scraper = MagicMock()
    app.state.engine_stats_scraper.get_engine_stats.return_value = {}
    app.state.request_stats_monitor = RequestStatsMonitor(60.0)
    app.state.otel_enabled = False
    app.state.semantic_cache_available = False
    app.state.callbacks = None
    app.state.external_provider_registry = None
    app.state.aiohttp_client_wrapper = client

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            lifespan="off",
            timeout_graceful_shutdown=1,
        )
    )
    with (
        patch.object(request_module, "get_service_discovery", return_value=discovery),
        patch.object(
            request_module, "is_request_rewriter_initialized", return_value=False
        ),
    ):
        serving = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.01)
        yield SimpleNamespace(
            port=server.servers[0].sockets[0].getsockname()[1],
            monitor=app.state.request_stats_monitor,
            engine=engine,
        )
        server.should_exit = True
        await serving
    await client.stop()


async def _post_then_disconnect(port, payload, request_id, *, after=0, until=None):
    """POST over a raw socket, then close it after `after` seconds or once
    `until` bytes arrive. Returns the disconnect time."""
    body = json.dumps(payload).encode()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        b"POST /v1/chat/completions HTTP/1.1\r\nHost: router\r\n"
        b"Content-Type: application/json\r\n"
        + f"X-Request-Id: {request_id}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        + body
    )
    await writer.drain()
    if until is not None:
        await reader.readuntil(until)
    else:
        await asyncio.sleep(after)
    writer.close()
    await writer.wait_closed()
    return time.monotonic()


async def _eventually(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.02)


def _drained(router):
    url = router.engine.url
    return (
        router.monitor.in_prefill_requests.get(url, 0) == 0
        and router.monitor.in_decoding_requests.get(url, 0) == 0
    )


async def test_non_stream_disconnect_before_headers_aborts_upstream(router):
    with patch.object(request_module, "logger") as logger:
        left = await _post_then_disconnect(
            router.port,
            {"model": "test-model", "messages": []},
            "early-leaver",
            after=0.5,
        )
        await _eventually(lambda: "early-leaver" in router.engine.closed)
        await _eventually(lambda: _drained(router))
        await _eventually(
            lambda: any(
                "Client disconnected before headers" in call.args[0]
                and "early-leaver" in call.args[0]
                for call in logger.info.call_args_list
            )
        )
    assert router.engine.closed["early-leaver"] - left < 1.0


async def test_non_stream_completion_is_unchanged(router):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://127.0.0.1:{router.port}/v1/chat/completions",
            json={"model": "test-model", "messages": [], "hold": 0.3},
        ) as response:
            assert response.status == 200
            assert (await response.json())["usage"] == {"completion_tokens": 1}
    url = router.engine.url
    await _eventually(lambda: router.monitor.finished_requests.get(url) == 1)
    assert _drained(router)


async def test_stream_disconnect_after_headers_still_aborts_upstream(router):
    left = await _post_then_disconnect(
        router.port,
        {"model": "test-model", "messages": [], "stream": True},
        "stream-leaver",
        until=b"data: ",
    )
    await _eventually(lambda: "stream-leaver" in router.engine.closed)
    await _eventually(lambda: _drained(router))
    assert router.engine.closed["stream-leaver"] - left < 1.0
