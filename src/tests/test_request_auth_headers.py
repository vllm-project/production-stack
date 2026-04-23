import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from vllm_router.services.request_service.request import (
    process_request,
    proxy_multipart_request,
)
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False):
        self.url = url
        self.model_names = model_names or ["whisper-model"]
        self.sleep = sleep


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


def _build_request(headers=None):
    state = MagicMock()
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.router.route_request.return_value = "http://whisper-engine"

    request = MagicMock()
    request.headers = headers or {}
    request.method = "POST"
    request.url = "http://router/v1/audio/transcriptions"
    request.query_params = {}
    request.app.state = state
    return request


def _mock_backend_response(payload: bytes):
    mock_content = MagicMock()

    async def iter_any():
        yield payload

    mock_content.iter_any = iter_any

    response = MagicMock()
    response.status = 200
    response.headers = MagicMock()
    response.headers.items.return_value = [("content-type", "application/json")]
    response.content = mock_content
    return response


@pytest.mark.asyncio
async def test_process_request_preserves_client_auth_and_normalizes_request_id():
    request = _build_request(
        {
            "content-type": "application/json",
            "authorization": "Bearer router-token",
            "x-request-id": "client-request-id",
        }
    )
    backend_response = _mock_backend_response(b'{"usage": {}}')

    client_request = MagicMock()
    client_request.__aenter__ = AsyncMock(return_value=backend_response)
    client_request.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.request = MagicMock(return_value=client_request)
    request.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    request_body = json.dumps({"model": "whisper-model", "stream": False}).encode()

    async for _ in process_request(
        request,
        request_body,
        "http://whisper-engine",
        "req-123",
        "/v1/chat/completions",
        MagicMock(),
    ):
        pass

    forwarded_headers = mock_client.request.call_args.kwargs["headers"]
    lowered_headers = {key.lower(): value for key, value in forwarded_headers.items()}

    assert lowered_headers["authorization"] == "Bearer router-token"
    assert forwarded_headers["X-Request-Id"] == "req-123"
    assert "x-request-id" not in forwarded_headers
    assert lowered_headers["content-type"] == "application/json"


@pytest.mark.asyncio
async def test_proxy_multipart_request_preserves_client_auth_without_stale_boundary():
    request = _build_request(
        {
            "content-type": "multipart/form-data; boundary=router-boundary",
            "authorization": "Bearer router-token",
            "X-Request-Id": "client-request-id",
            "x-custom-header": "keep-me",
        }
    )
    backend_response = MagicMock()
    backend_response.status = 200
    backend_response.headers.items.return_value = [("content-type", "application/json")]
    backend_response.json = AsyncMock(return_value={"ok": True})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=backend_response)
    request.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = [EndpointInfo("http://engine")]

    form_data = aiohttp.FormData()
    form_data.add_field("file", b"audio-bytes", filename="sample.wav")
    form_data.add_field("model", "whisper-model")

    with patch(
        "vllm_router.services.request_service.request.get_service_discovery",
        return_value=service_discovery,
    ):
        response = await proxy_multipart_request(
            form_data,
            "whisper-model",
            "/v1/audio/transcriptions",
            request,
        )

    forwarded_headers = mock_client.post.await_args.kwargs["headers"]
    lowered_headers = {key.lower(): value for key, value in forwarded_headers.items()}

    assert response.status_code == 200
    assert lowered_headers["authorization"] == "Bearer router-token"
    assert forwarded_headers["X-Request-Id"] == "client-request-id"
    assert "x-request-id" not in forwarded_headers
    assert forwarded_headers["x-custom-header"] == "keep-me"
    assert "content-type" not in lowered_headers
