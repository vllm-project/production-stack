from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from starlette.requests import Request

from vllm_router.services.request_service.request import route_sleep_wakeup_request


@pytest.fixture
async def engine():
    """A stand-in vLLM engine that records the query string of each call."""
    seen = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(list(request.query.items()))
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/wake_up", handler)
    app.router.add_post("/sleep", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", seen
    await runner.cleanup()


def _router_request(path: str, query_string: bytes) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": query_string,
        "headers": [],
    }
    return Request(scope, receive)


def _service_discovery(url: str) -> MagicMock:
    endpoint = MagicMock()
    endpoint.Id = "engine-1"
    endpoint.url = url
    endpoint.pod_name = "pod-1"
    sd = MagicMock()
    sd.get_endpoint_info.return_value = [endpoint]
    return sd


async def test_wake_up_forwards_every_tags_value(engine):
    url, seen = engine
    request = _router_request("/wake_up", b"id=engine-1&tags=weights&tags=kv_cache")
    with patch(
        "vllm_router.services.request_service.request.get_service_discovery",
        return_value=_service_discovery(url),
    ):
        response = await route_sleep_wakeup_request(request, "/wake_up", None)

    assert response.status_code == 200
    assert seen == [[("tags", "weights"), ("tags", "kv_cache")]]


async def test_sleep_forwards_params_without_router_id(engine):
    url, seen = engine
    request = _router_request("/sleep", b"id=engine-1&level=2&mode=wait")
    with patch(
        "vllm_router.services.request_service.request.get_service_discovery",
        return_value=_service_discovery(url),
    ):
        response = await route_sleep_wakeup_request(request, "/sleep", None)

    assert response.status_code == 200
    assert seen == [[("level", "2"), ("mode", "wait")]]
