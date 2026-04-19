"""
Tests for transcription streaming path in proxy_multipart_request:

1. stream=True returns a StreamingResponse that proxies SSE chunks.
2. stream=False (default) returns a JSONResponse (backward compatible).
3. Stats hooks are called correctly for streaming transcription.
4. Upstream response closed after normal completion.
5. Upstream response closed when consumer aborts mid-stream (aclose).
6. Connection failure before headers updates request stats.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import FormData

from vllm_router.routers.routing_logic import RoundRobinRouter
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["whisper-model"]
        self.sleep = sleep
        self.Id = Id


ENDPOINTS = [EndpointInfo(url="http://whisper-engine")]


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


@pytest.fixture
def setup_mocks():
    sd = MagicMock()
    sd.get_endpoint_info.return_value = ENDPOINTS
    sd.aliases = None

    with patch(
        "vllm_router.services.request_service.request.get_service_discovery",
        return_value=sd,
    ):
        yield sd


def _make_mock_request():
    router = RoundRobinRouter()
    router.max_instance_failover_reroute_attempts = 0

    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.request_stats_monitor.on_new_request = MagicMock()
    state.request_stats_monitor.on_request_response = MagicMock()
    state.request_stats_monitor.on_request_complete = MagicMock()
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None

    req = MagicMock()
    req.headers = {
        "content-type": "multipart/form-data",
        "authorization": "Bearer test-key",
    }
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/audio/transcriptions"
    req.app.state = state

    return req


def _make_backend_response(chunks, content_type="text/event-stream", status=200):
    async def iter_any():
        for c in chunks:
            yield c

    content = MagicMock()
    content.iter_any = iter_any

    resp = MagicMock()
    resp.status = status
    resp.headers = {"content-type": content_type, "x-request-id": "test-123"}
    resp.content = content
    resp.close = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_transcription_streaming_returns_streaming_response(setup_mocks):
    req = _make_mock_request()

    mock_backend_response = _make_backend_response(
        [b'data: {"text": "Hello"}\n\n', b'data: {"text": " World"}\n\n']
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    from fastapi.responses import StreamingResponse

    assert isinstance(resp, StreamingResponse)
    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_transcription_non_streaming_returns_json_response(setup_mocks):
    req = _make_mock_request()

    mock_backend_response = MagicMock()
    mock_backend_response.status = 200
    mock_backend_response.headers = {
        "content-type": "application/json",
        "x-request-id": "test-123",
    }
    mock_backend_response.json = AsyncMock(
        return_value={"text": "Hello world transcription"}
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=False
    )

    from fastapi.responses import JSONResponse

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 200
    assert resp.body == b'{"text":"Hello world transcription"}'


@pytest.mark.asyncio
async def test_streaming_calls_stats_hooks(setup_mocks):
    req = _make_mock_request()

    mock_backend_response = _make_backend_response(
        [b'data: {"text": "Hello"}\n\n', b'data: {"text": " World"}\n\n']
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    req.app.state.request_stats_monitor.on_new_request.assert_called_once()

    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)

    req.app.state.request_stats_monitor.on_request_response.assert_called_once()
    req.app.state.request_stats_monitor.on_request_complete.assert_called_once()
    mock_backend_response.close.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_preserves_content_type(setup_mocks):
    req = _make_mock_request()

    mock_backend_response = _make_backend_response(
        [b'data: {"text": "Hello"}\n\n'], content_type="application/x-ndjson"
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    assert resp.media_type == "application/x-ndjson"


@pytest.mark.asyncio
async def test_streaming_uses_aiohttp_multipart_boundary(setup_mocks):
    req = _make_mock_request()

    mock_backend_response = _make_backend_response([b'data: {"text": "Hello"}\n\n'])

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    call_args = mock_client.post.call_args
    assert call_args is not None
    kwargs = call_args[1] if call_args[1] else {}
    assert kwargs.get("headers") is None


@pytest.mark.asyncio
async def test_streaming_closes_upstream_on_full_consumption(setup_mocks):
    req = _make_mock_request()

    mock_backend_response = _make_backend_response(
        [b'data: {"text": "Hello"}\n\n', b'data: {"text": " World"}\n\n']
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)

    assert len(chunks) == 2
    mock_backend_response.close.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_closes_upstream_on_consumer_abort(setup_mocks):
    """Downstream client disconnects mid-stream: body_iterator.aclose() must
    run the finally block and close the upstream response."""
    req = _make_mock_request()

    mock_backend_response = _make_backend_response(
        [
            b'data: {"text": "chunk1"}\n\n',
            b'data: {"text": "chunk2"}\n\n',
            b'data: {"text": "chunk3"}\n\n',
        ]
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    body_iter = resp.body_iterator
    first = await body_iter.__anext__()
    assert first == b'data: {"text": "chunk1"}\n\n'

    await body_iter.aclose()

    mock_backend_response.close.assert_called_once()
    req.app.state.request_stats_monitor.on_request_complete.assert_called_once()


@pytest.mark.asyncio
async def test_streaming_stats_on_connection_failure(setup_mocks):
    req = _make_mock_request()

    import aiohttp

    err = aiohttp.ClientConnectorError(
        connection_key=MagicMock(), os_error=OSError("connection refused")
    )

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=err)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import proxy_multipart_request

    form_data = FormData()
    form_data.add_field(
        "file", b"fake-audio", filename="test.wav", content_type="audio/wav"
    )
    form_data.add_field("model", "whisper-model")
    form_data.add_field("stream", "true")

    resp = await proxy_multipart_request(
        form_data, "whisper-model", "/v1/audio/transcriptions", req, stream=True
    )

    from fastapi.responses import JSONResponse

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 503
    req.app.state.request_stats_monitor.on_new_request.assert_called_once()
    req.app.state.request_stats_monitor.on_request_complete.assert_called_once()
