"""
Audio routing and response handling in route_general_request:

1. The StreamingResponse media_type is taken from the backend Content-Type header
   instead of being hardcoded as "text/event-stream".
2. Binary (non-UTF-8) response bodies do not crash token-tracking in process_request.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.datastructures import QueryParams

from vllm_router.routers.routing_logic import (
    PriorityRouter,
    RoundRobinRouter,
)
from vllm_router.services.request_service import request as request_service
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["tts-model"]
        self.sleep = sleep
        self.Id = Id


def _make_mock_headers(content_type: str):
    h = MagicMock()
    h.items.return_value = [("content-type", content_type)]
    h.get.side_effect = lambda key, default=None: (
        content_type if str(key).lower() == "content-type" else default
    )
    return h


ENDPOINTS = [EndpointInfo(url="http://tts-engine")]


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


@pytest.fixture
def setup():
    """Yield a (request, router) pair with all app-state dependencies patched."""
    router = RoundRobinRouter()
    router.max_instance_failover_reroute_attempts = 0

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
    state.external_provider_registry = None

    req = MagicMock()
    req.headers = {"content-type": "application/json"}
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/audio/speech"
    req.app.state = state

    async def body():
        return json.dumps(
            {"model": "tts-model", "input": "Hello", "voice": "alloy", "stream": False}
        ).encode()

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


@pytest.mark.asyncio
async def test_audio_content_type_forwarded(setup):
    """StreamingResponse media_type must match the backend Content-Type for audio."""
    req, _ = setup
    mock_headers = _make_mock_headers("audio/wav")

    async def audio_backend(*a, **kw):
        yield mock_headers, 200
        yield b"\xff\xfe\x00\x00binary-audio-data"

    with patch(
        "vllm_router.services.request_service.request.process_request",
        side_effect=audio_backend,
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/audio/speech", MagicMock())

    assert resp.status_code == 200
    assert resp.media_type == "audio/wav"


@pytest.mark.asyncio
async def test_sse_content_type_preserved(setup):
    """When the backend sends text/event-stream the media_type is still correct."""
    req, _ = setup
    mock_headers = _make_mock_headers("text/event-stream")

    async def sse_backend(*a, **kw):
        yield mock_headers, 200
        yield b"data: {}\n\n"

    with patch(
        "vllm_router.services.request_service.request.process_request",
        side_effect=sse_backend,
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_fallback_to_event_stream_when_no_content_type(setup):
    """When the backend sends no Content-Type, fall back to text/event-stream."""
    req, _ = setup

    h = MagicMock()
    h.items.return_value = []  # no content-type header
    h.get.side_effect = lambda _, default=None: default

    async def no_ct_backend(*a, **kw):
        yield h, 200
        yield b"data: {}\n\n"

    with patch(
        "vllm_router.services.request_service.request.process_request",
        side_effect=no_ct_backend,
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_binary_response_does_not_raise(setup):
    """
    process_request must not raise UnicodeDecodeError when the backend returns
    binary (non-UTF-8) data for a non-streaming request (e.g. /v1/audio/speech).
    """
    req, _ = setup

    # Raw binary audio bytes that are not valid UTF-8
    binary_audio = bytes([0xC0, 0xAF, 0xFF, 0xFE] * 100)

    # Build a real-enough aiohttp mock so process_request can iterate chunks
    mock_content = MagicMock()

    async def iter_any():
        yield binary_audio

    mock_content.iter_any = iter_any

    mock_backend_response = MagicMock()
    mock_backend_response.status = 200
    mock_backend_response.headers = MagicMock()
    mock_backend_response.headers.items.return_value = [("content-type", "audio/wav")]
    mock_backend_response.content = mock_content

    # Make the context manager work
    from unittest.mock import AsyncMock

    mock_client_request = MagicMock()
    mock_client_request.__aenter__ = AsyncMock(return_value=mock_backend_response)
    mock_client_request.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.request = MagicMock(return_value=mock_client_request)

    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    from vllm_router.services.request_service.request import process_request

    request_body = json.dumps(
        {"model": "tts-model", "input": "Hello", "voice": "alloy", "stream": False}
    ).encode()

    # Collect all yielded values — this must not raise
    chunks = []
    async for item in process_request(
        req,
        request_body,
        "http://tts-engine",
        "req-001",
        "/v1/audio/speech",
        MagicMock(),
    ):
        chunks.append(item)

    # First yield is (headers, status), subsequent yields are bytes chunks
    assert chunks[0][1] == 200  # status
    assert binary_audio in chunks


@pytest.fixture
def backend_request(setup):
    request, _ = setup
    send = request.app.state.aiohttp_client_wrapper().request
    response = MagicMock(status=200, headers={"content-type": "application/json"})
    response.content.iter_any.return_value.__aiter__.return_value = [b"{}"]
    send.return_value.__aenter__.return_value = response
    return send


@pytest.mark.asyncio
async def test_bodyless_voices_get_routes_and_forwards_the_query_model(
    setup, backend_request
):
    request, _ = setup
    request.method = "GET"
    request.body = AsyncMock(return_value=b"")
    request.query_params = QueryParams("tag=a&model=old&id=engine-1&tag=b&model=alias")
    request.app.state.router = PriorityRouter()
    request.app.state.router.max_instance_failover_reroute_attempts = 0
    request_service.is_request_rewriter_initialized.return_value = True
    discovery = request_service.get_service_discovery()
    discovery.aliases = {"alias": "tts-model"}
    discovery.get_endpoint_info.return_value = [
        EndpointInfo("http://tts-engine", Id="engine-1")
    ]

    with patch.object(request_service.request_latency_seconds, "labels") as latency:
        response = await request_service.route_general_request(
            request, "/v1/audio/voices", None
        )
        assert response.status_code == 200
        assert [chunk async for chunk in response.body_iterator] == [b"{}"]
        latency.assert_called_once_with(
            server="http://tts-engine", model="tts-model", status="success"
        )

    forwarded = backend_request.call_args.kwargs
    assert forwarded["method"] == "GET"
    assert forwarded["url"] == "http://tts-engine/v1/audio/voices"
    assert forwarded["data"] is None
    assert forwarded["params"] == [("tag", "a"), ("model", "tts-model"), ("tag", "b")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "endpoint", "body", "query", "missing"),
    [
        ("GET", "/v1/audio/voices", b"", "", "query parameter"),
        ("GET", "/v1/audio/voices", b"{}", "model=tts-model", "in request body"),
        ("POST", "/v1/audio/speech", b"", "model=tts-model", "in request body"),
    ],
)
async def test_missing_voice_or_body_model(
    setup, method, endpoint, body, query, missing
):
    request, _ = setup
    request.method = method
    request.body = AsyncMock(return_value=body)
    request.query_params = QueryParams(query)
    response = await request_service.route_general_request(request, endpoint, None)
    assert response.status_code == 400
    assert missing in json.loads(response.body)["error"]
    assert response.headers["X-Request-Id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "endpoint"),
    [("POST", "/v1/chat/completions"), ("GET", "/v1/audio/voices")],
)
async def test_requests_with_a_json_body_do_not_forward_query_params(
    setup, backend_request, method, endpoint
):
    request, _ = setup
    request.method = method
    body = b'{"model":"tts-model"}'
    request.body = AsyncMock(return_value=body)
    request.query_params = QueryParams("model=other&format=example")

    response = await request_service.route_general_request(request, endpoint, None)
    assert response.status_code == 200
    assert [chunk async for chunk in response.body_iterator] == [b"{}"]
    forwarded = backend_request.call_args.kwargs
    assert forwarded["data"] == body
    assert forwarded.get("params") is None


@pytest.mark.asyncio
async def test_bodyless_voices_get_uses_local_backends_only(setup, backend_request):
    request, _ = setup
    request.method = "GET"
    request.body = AsyncMock(return_value=b"")
    request.query_params = QueryParams("model=external")
    discovery = request_service.get_service_discovery()
    discovery.get_endpoint_info.return_value = []
    discovery.has_ever_seen_model.return_value = False
    provider = MagicMock()
    provider.is_external_model.return_value = True
    request.app.state.external_provider_registry = provider

    response = await request_service.route_general_request(
        request, "/v1/audio/voices", None
    )
    assert response.status_code == 404
    provider.lookup_adapter.assert_not_called()
    backend_request.assert_not_called()
