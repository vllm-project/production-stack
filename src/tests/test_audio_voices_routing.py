"""
GET /v1/audio/voices (vLLM-Omni) carries no request body, so the model can
only be named in the query string (?model=...). The router must route it and
forward a body-less GET instead of rejecting it with a 400.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vllm_router.routers.routing_logic import PriorityRouter, RoundRobinRouter
from vllm_router.services.request_service.request import route_general_request
from vllm_router.utils import SingletonABCMeta

VOICES = {"voices": ["aiden", "vivian"], "uploaded_voices": []}


class EndpointInfo:
    def __init__(self, url, model_names):
        self.url = url
        self.model_names = model_names
        self.sleep = False
        self.Id = None


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


def _backend_client():
    content = MagicMock()

    async def iter_any():
        yield json.dumps(VOICES).encode()

    content.iter_any = iter_any
    response = MagicMock()
    response.status = 200
    response.headers = MagicMock()
    response.headers.items.return_value = [("content-type", "application/json")]
    response.headers.get.side_effect = lambda key, default=None: (
        "application/json" if str(key).lower() == "content-type" else default
    )
    response.content = content

    request_cm = MagicMock()
    request_cm.__aenter__ = AsyncMock(return_value=response)
    request_cm.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock()
    client.request = MagicMock(return_value=request_cm)
    return client


def _make_request(router, query_params, aliases=None, body=b""):
    sd = MagicMock()
    sd.get_endpoint_info.return_value = [
        EndpointInfo("http://tts-engine", ["tts-model"]),
        EndpointInfo("http://chat-engine", ["chat-model"]),
    ]
    sd.aliases = aliases
    sd.has_ever_seen_model.return_value = False

    client = _backend_client()
    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None
    state.external_provider_registry = None
    state.aiohttp_client_wrapper.return_value = client

    req = MagicMock()
    req.headers = {}
    req.query_params = query_params
    req.method = "GET"
    req.url = "http://router/v1/audio/voices"
    req.app.state = state
    req.body = AsyncMock(return_value=body)
    return req, sd, client


async def _route(req, sd, rewriter_on=True):
    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=sd,
        ),
        patch(
            "vllm_router.services.request_service.request.is_request_rewriter_initialized",
            return_value=rewriter_on,
        ),
        patch(
            "vllm_router.services.request_service.request.get_request_rewriter",
            side_effect=AssertionError("a body-less GET must not be rewritten"),
        ),
    ):
        resp = await route_general_request(req, "/v1/audio/voices", MagicMock())
        body = b""
        if resp.status_code == 200:
            async for chunk in resp.body_iterator:
                body += chunk
        else:
            body = resp.body
    return resp, json.loads(body)


def _make_router(router_cls):
    router = router_cls()
    router.max_instance_failover_reroute_attempts = 0
    return router


@pytest.mark.asyncio
@pytest.mark.parametrize("router_cls", [RoundRobinRouter, PriorityRouter])
async def test_voices_get_routes_by_model_query_param(router_cls):
    req, sd, client = _make_request(_make_router(router_cls), {"model": "tts-model"})

    resp, body = await _route(req, sd)

    assert resp.status_code == 200
    assert body == VOICES
    kwargs = client.request.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["url"] == "http://tts-engine/v1/audio/voices"
    assert not kwargs["data"]


@pytest.mark.asyncio
async def test_voices_get_resolves_alias_without_adding_a_body():
    req, sd, client = _make_request(
        _make_router(RoundRobinRouter),
        {"model": "voice"},
        aliases={"voice": "tts-model"},
    )

    resp, body = await _route(req, sd)

    assert resp.status_code == 200
    kwargs = client.request.call_args.kwargs
    assert kwargs["url"] == "http://tts-engine/v1/audio/voices"
    assert not kwargs["data"]


@pytest.mark.asyncio
async def test_voices_get_unknown_model_is_404():
    req, sd, client = _make_request(_make_router(RoundRobinRouter), {"model": "nope"})

    resp, body = await _route(req, sd)

    assert resp.status_code == 404
    client.request.assert_not_called()


@pytest.mark.asyncio
async def test_voices_get_without_model_is_400():
    req, sd, client = _make_request(_make_router(RoundRobinRouter), {})

    resp, body = await _route(req, sd)

    assert resp.status_code == 400
    assert "model" in body["error"]
    client.request.assert_not_called()


@pytest.mark.asyncio
async def test_body_model_still_wins_over_query_param():
    req, sd, client = _make_request(
        _make_router(RoundRobinRouter),
        {"model": "chat-model"},
        body=json.dumps({"model": "tts-model"}).encode(),
    )

    resp, body = await _route(req, sd, rewriter_on=False)

    assert resp.status_code == 200
    assert client.request.call_args.kwargs["url"] == "http://tts-engine/v1/audio/voices"


@pytest.mark.asyncio
async def test_voices_get_body_without_model_falls_back_to_query_param():
    req, sd, client = _make_request(
        _make_router(RoundRobinRouter),
        {"model": "tts-model"},
        body=json.dumps({"voice": "alloy"}).encode(),
    )

    resp, body = await _route(req, sd, rewriter_on=False)

    assert resp.status_code == 200
    assert client.request.call_args.kwargs["url"] == "http://tts-engine/v1/audio/voices"
