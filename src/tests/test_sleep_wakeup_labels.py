from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from starlette.requests import Request

from vllm_router.service_discovery import StaticServiceDiscovery
from vllm_router.services.request_service.request import route_sleep_wakeup_request


@pytest.fixture
async def engine_url():
    """A stand-in vLLM engine that accepts /sleep and /wake_up."""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({})

    app = web.Application()
    app.router.add_post("/sleep", handler)
    app.router.add_post("/wake_up", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    await runner.cleanup()


def _router_request(path: str, engine_id: str) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": f"id={engine_id}".encode(),
        "headers": [],
    }
    return Request(scope, receive)


async def _call(path, engine_id, service_discovery):
    with patch(
        "vllm_router.services.request_service.request.get_service_discovery",
        return_value=service_discovery,
    ):
        return await route_sleep_wakeup_request(
            _router_request(path, engine_id), path, None
        )


async def test_service_name_discovery_labels_the_service(engine_url):
    endpoint = MagicMock()
    endpoint.Id = "engine-1"
    endpoint.url = engine_url
    endpoint.pod_name = None
    endpoint.service_name = "vllm-engine-service"
    sd = MagicMock()
    sd.get_endpoint_info.return_value = [endpoint]

    response = await _call("/sleep", "engine-1", sd)
    assert response.status_code == 200
    sd.add_sleep_label.assert_called_once_with("vllm-engine-service")

    response = await _call("/wake_up", "engine-1", sd)
    assert response.status_code == 200
    sd.remove_sleep_label.assert_called_once_with("vllm-engine-service")


async def test_static_discovery_answers_sleep_and_wake_up(engine_url):
    sd = StaticServiceDiscovery(
        app=None,
        urls=[engine_url, "http://127.0.0.1:1"],
        models=["m", "m"],
    )
    engine_id = sd.get_endpoint_info()[0].Id

    response = await _call("/sleep", engine_id, sd)
    assert response.status_code == 200

    response = await _call("/wake_up", engine_id, sd)
    assert response.status_code == 200
