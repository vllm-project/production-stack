"""Tests for the standardized ``route_request`` signature (issue #1022).

Every router must expose ``async def route_request(self, endpoints,
engine_stats, request_stats, request, request_json)`` so that call sites can
always ``await`` and always pass ``request_json`` without isinstance-based
dispatch guards.
"""

import inspect
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    DisaggregatedPrefillRouter,
    KvawareRouter,
    PrefixAwareRouter,
    RoundRobinRouter,
    RoutingInterface,
    SessionRouter,
)
from vllm_router.utils import SingletonABCMeta

ALL_ROUTER_CLASSES = [
    RoundRobinRouter,
    SessionRouter,
    KvawareRouter,
    PrefixAwareRouter,
    DisaggregatedPrefillRouter,
    DisaggregatedPrefillOrchestratedRouter,
]


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["test-model"]
        self.sleep = sleep
        self.Id = Id


class RecordingAsyncRouter(RoutingInterface):
    """A router that is NOT in any isinstance whitelist at the call sites.

    It records the ``request_json`` it receives, so tests can verify that the
    call sites actually awaited the coroutine (the body of an un-awaited
    coroutine never runs) and passed the request body through.
    """

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.received_request_jsons = []
        self.max_instance_failover_reroute_attempts = 0
        self._initialized = True

    async def route_request(
        self,
        endpoints,
        engine_stats,
        request_stats,
        request,
        request_json=None,
    ) -> str:
        self.received_request_jsons.append(request_json)
        return endpoints[0].url


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


@pytest.mark.parametrize("router_cls", ALL_ROUTER_CLASSES)
def test_route_request_is_coroutine_function(router_cls):
    assert inspect.iscoroutinefunction(
        router_cls.route_request
    ), f"{router_cls.__name__}.route_request must be an async def"


@pytest.mark.parametrize("router_cls", ALL_ROUTER_CLASSES)
def test_route_request_accepts_request_json(router_cls):
    params = inspect.signature(router_cls.route_request).parameters
    assert "request_json" in params, (
        f"{router_cls.__name__}.route_request must accept a request_json" " parameter"
    )
    param_names = list(params)
    assert param_names[:6] == [
        "self",
        "endpoints",
        "engine_stats",
        "request_stats",
        "request",
        "request_json",
    ], f"{router_cls.__name__}.route_request has unexpected parameter order"


def test_base_interface_route_request_is_async_with_request_json():
    assert inspect.iscoroutinefunction(RoutingInterface.route_request)
    assert (
        "request_json" in inspect.signature(RoutingInterface.route_request).parameters
    )


@pytest.mark.asyncio
async def test_roundrobin_routes_via_awaited_path():
    router = RoundRobinRouter()
    endpoints = [EndpointInfo(url="http://engine1"), EndpointInfo(url="http://engine2")]
    request = MagicMock()

    urls = [
        await router.route_request(endpoints, {}, {}, request, {}) for _ in range(4)
    ]

    assert urls == ["http://engine1", "http://engine2"] * 2


@pytest.mark.asyncio
async def test_route_general_request_awaits_any_router_and_passes_request_json():
    """Call-site dispatch must not depend on the router's concrete type."""
    router = RecordingAsyncRouter()

    sd = MagicMock()
    sd.get_endpoint_info.return_value = [
        EndpointInfo(url="http://engine1"),
        EndpointInfo(url="http://engine2"),
    ]
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
    req.url = "http://router/v1/chat/completions"
    req.app.state = state

    request_body = {"model": "test-model", "stream": False}

    async def body():
        return json.dumps(request_body).encode()

    req.body = body

    mock_headers = MagicMock()
    mock_headers.items.return_value = [("content-type", "text/event-stream")]

    async def ok(*args, **kwargs):
        yield mock_headers, 200
        yield b"done"

    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=sd,
        ),
        patch(
            "vllm_router.services.request_service.request.is_request_rewriter_initialized",
            return_value=False,
        ),
        patch(
            "vllm_router.services.request_service.request.process_request",
            side_effect=ok,
        ) as mock_process,
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200
    # The coroutine body only runs when awaited, so this proves the call site
    # awaited route_request and forwarded the parsed JSON body.
    assert router.received_request_jsons == [request_body]
    # process_request must receive the resolved URL string, not a coroutine.
    assert mock_process.call_args.args[2] == "http://engine1"


@pytest.mark.asyncio
async def test_proxy_multipart_request_awaits_route_request_with_request_json():
    router = RecordingAsyncRouter()

    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.otel_enabled = False

    req = MagicMock()
    req.headers = {"content-type": "multipart/form-data; boundary=router-boundary"}
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/audio/transcriptions"
    req.app.state = state

    backend_response = MagicMock()
    backend_response.status = 200
    backend_response.headers.items.return_value = [("content-type", "application/json")]
    backend_response.json = AsyncMock(return_value={"ok": True})

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=backend_response)
    req.app.state.aiohttp_client_wrapper = MagicMock(return_value=mock_client)

    sd = MagicMock()
    sd.get_endpoint_info.return_value = [
        EndpointInfo(url="http://engine1", model_names=["whisper-model"])
    ]

    form_data = aiohttp.FormData()
    form_data.add_field("file", b"audio-bytes", filename="sample.wav")
    form_data.add_field("model", "whisper-model")

    with patch(
        "vllm_router.services.request_service.request.get_service_discovery",
        return_value=sd,
    ):
        from vllm_router.services.request_service.request import (
            proxy_multipart_request,
        )

        response = await proxy_multipart_request(
            form_data,
            "whisper-model",
            "/v1/audio/transcriptions",
            req,
        )

    assert response.status_code == 200
    # Proves the call site awaited route_request and passed a request_json
    # ({} because multipart requests carry no JSON body).
    assert router.received_request_jsons == [{}]
    # And the backend was called with the resolved URL string.
    assert (
        mock_client.post.await_args.args[0] == "http://engine1/v1/audio/transcriptions"
    )
