"""Tests for GET /v1/audio/voices routing.

vLLM-omni's voices endpoint is a body-less GET. The router must take the
model from the query string, skip body rewrites, and forward a GET with
no body. POST routes still require a JSON body field.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.routers.routing_logic import RoundRobinRouter
from vllm_router.utils import SingletonABCMeta


class EndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["tts"]
        self.sleep = sleep
        self.Id = Id


ENDPOINTS = [EndpointInfo(url="http://tts-engine")]


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


@contextmanager
def _make_request(
    *,
    method="GET",
    body=b"",
    query_params=None,
    aliases=None,
):
    router = RoundRobinRouter()
    router.max_instance_failover_reroute_attempts = 0

    sd = MagicMock()
    sd.get_endpoint_info.return_value = ENDPOINTS
    sd.aliases = aliases
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
    req.headers = {}
    req.query_params = query_params or {}
    req.method = method
    req.url = "http://router/v1/audio/voices"
    req.app.state = state

    async def _body():
        return body

    req.body = _body

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
    try:
        yield req, sd
    finally:
        for p in patches:
            p.stop()


def _json_backend(captured):
    async def backend(*args, **kwargs):
        captured["body"] = args[1] if len(args) > 1 else kwargs.get("body")
        captured["backend_url"] = (
            args[2] if len(args) > 2 else kwargs.get("backend_url")
        )
        headers = MagicMock()
        headers.items.return_value = [("content-type", "application/json")]
        headers.get.side_effect = lambda key, default=None: (
            "application/json" if str(key).lower() == "content-type" else default
        )
        yield headers, 200
        yield b'{"voices":["aiden"]}'

    return backend


@pytest.mark.asyncio
async def test_get_voices_without_model_returns_400():
    with _make_request(query_params={}) as (req, _):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/audio/voices", MagicMock())
    assert resp.status_code == 400
    assert "model" in json.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_post_ignores_query_model_and_requires_body():
    with _make_request(
        method="POST",
        body=b"",
        query_params={"model": "tts"},
    ) as (req, _):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/audio/voices", MagicMock())
    assert resp.status_code == 400
    assert "model" in json.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_get_voices_uses_query_model_and_forwards_empty_body():
    captured = {}
    with (
        _make_request(query_params={"model": "tts"}) as (req, _),
        patch(
            "vllm_router.services.request_service.request.process_request",
            side_effect=_json_backend(captured),
        ),
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/audio/voices", MagicMock())

    assert resp.status_code == 200
    assert captured["body"] == b""
    assert captured["backend_url"] == "http://tts-engine"


@pytest.mark.asyncio
async def test_get_voices_body_model_wins_over_query():
    captured = {}
    with (
        _make_request(
            body=json.dumps({"model": "tts"}).encode(),
            query_params={"model": "other-model"},
        ) as (req, sd),
        patch(
            "vllm_router.services.request_service.request.process_request",
            side_effect=_json_backend(captured),
        ),
    ):
        sd.get_endpoint_info.return_value = [
            EndpointInfo(url="http://tts-engine", model_names=["tts"]),
            EndpointInfo(url="http://other-engine", model_names=["other-model"]),
        ]
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/audio/voices", MagicMock())

    assert resp.status_code == 200
    assert captured["backend_url"] == "http://tts-engine"


@pytest.mark.asyncio
async def test_get_voices_resolves_alias_without_rewriting_empty_body():
    captured = {}
    with (
        _make_request(
            query_params={"model": "my-tts"},
            aliases={"my-tts": "tts"},
        ) as (req, _),
        patch(
            "vllm_router.services.request_service.request.process_request",
            side_effect=_json_backend(captured),
        ),
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/audio/voices", MagicMock())

    assert resp.status_code == 200
    assert captured["body"] == b""
    assert captured["backend_url"] == "http://tts-engine"
