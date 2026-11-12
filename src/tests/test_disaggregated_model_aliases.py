"""P/D engines accept only canonical names; aliases belong to the Router."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import aiohttp
import httpx
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi import FastAPI

from vllm_router.aiohttp_client import AiohttpClientWrapper
from vllm_router.routers.main_router import main_router
from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    DisaggregatedPrefillRouter,
    RoundRobinRouter,
)
from vllm_router.services.request_service import request as request_module
from vllm_router.utils import resolve_model_alias

MODEL = "canonical-model"
ALIAS = "client-alias"
APIS = ["/v1/chat/completions", "/v1/completions"]


@asynccontextmanager
async def backend(role, seen):
    async def infer(request):
        body = await request.json()
        seen.append((role, body))
        if body.get("model") != MODEL:
            return web.json_response({"error": "model not found"}, status=404)
        if role == "prefill":
            return web.json_response({"kv_transfer_params": {"remote_engine_id": "p"}})
        if body.get("stream"):
            return web.Response(
                text='data: {"model":"canonical-model","choices":[]}\n\ndata: [DONE]\n\n',
                content_type="text/event-stream",
            )
        return web.json_response({"model": MODEL, "choices": []})

    app = web.Application()
    for api in APIS:
        app.router.add_post(api, infer)
    async with TestServer(app) as server:
        yield str(server.make_url("/")).rstrip("/")


@asynccontextmanager
async def router_client(mode, aliases, monkeypatch):
    seen = []
    async with backend("prefill", seen) as p, backend("decode", seen) as d:
        cls = {
            "basic": DisaggregatedPrefillRouter,
            "orchestrated": DisaggregatedPrefillOrchestratedRouter,
            "ordinary": RoundRobinRouter,
        }[mode]
        router = object.__new__(cls)
        if mode != "ordinary":
            cls.__init__(router, ["prefill"], ["decode"])
        else:
            cls.__init__(router)
            router.max_instance_failover_reroute_attempts = 0
        endpoints = [
            SimpleNamespace(
                url=p, model_label="prefill", model_names=[MODEL], sleep=False
            ),
            SimpleNamespace(
                url=d, model_label="decode", model_names=[MODEL], sleep=False
            ),
        ]
        discovery = SimpleNamespace(
            aliases=aliases,
            get_endpoint_info=lambda: (
                endpoints if mode != "ordinary" else endpoints[1:]
            ),
            has_ever_seen_model=lambda model: model == MODEL,
        )
        monkeypatch.setattr(request_module, "get_service_discovery", lambda: discovery)
        monkeypatch.setattr(
            request_module, "is_request_rewriter_initialized", lambda: False
        )
        app = FastAPI()
        app.include_router(main_router)
        app.state.router = router
        app.state.otel_enabled = False
        app.state.semantic_cache_available = False
        app.state.callbacks = None
        app.state.external_provider_registry = None
        app.state.engine_stats_scraper = SimpleNamespace(get_engine_stats=lambda: {})
        app.state.request_stats_monitor = MagicMock()
        app.state.request_stats_monitor.get_request_stats.return_value = {}
        wrapper = AiohttpClientWrapper()
        wrapper.start()
        app.state.aiohttp_client_wrapper = wrapper
        try:
            async with (
                aiohttp.ClientSession(base_url=p) as pc,
                aiohttp.ClientSession(base_url=d) as dc,
            ):
                app.state.prefill_client = pc
                app.state.decode_client = dc
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://router"
                ) as client:
                    yield client, seen
        finally:
            await wrapper.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["basic", "orchestrated", "ordinary"])
@pytest.mark.parametrize("api", APIS)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model", [MODEL, ALIAS])
async def test_alias_reaches_engines_as_canonical_name(
    monkeypatch, mode, api, stream, model
):
    async with router_client(mode, {ALIAS: MODEL}, monkeypatch) as (client, seen):
        response = await client.post(
            api,
            json={
                "model": model,
                "prompt": "hello",
                "messages": [],
                "stream": stream,
                "max_tokens": 8,
            },
        )
        assert response.status_code == 200, response.text
        if stream:
            # The basic PD route currently labels all responses application/json.
            if mode != "basic":
                assert response.headers["content-type"].startswith("text/event-stream")
            assert response.content.endswith(b"data: [DONE]\n\n")
            for line in response.text.splitlines():
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    assert json.loads(line[5:])["model"] == MODEL
        else:
            assert response.json()["model"] == MODEL
    assert [role for role, _ in seen] == (
        ["decode"] if mode == "ordinary" else ["prefill", "decode"]
    )
    assert all(body["model"] == MODEL for _, body in seen)
    decoded = seen[-1][1]
    assert decoded["max_tokens"] == 8 and decoded["stream"] == stream
    if mode != "ordinary":
        assert seen[0][1]["max_tokens"] == 1 and seen[0][1]["stream"] is False
    if mode == "orchestrated":
        assert decoded["kv_transfer_params"]["remote_engine_id"] == "p"
        assert decoded["kv_transfer_params"]["remote_host"] == "127.0.0.1"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["basic", "orchestrated"])
@pytest.mark.parametrize(
    "aliases,model",
    [
        (None, ALIAS),
        ({ALIAS: MODEL}, "CLIENT-ALIAS"),
        ({ALIAS: MODEL}, "unknown"),
        ({ALIAS: "next", "next": MODEL}, ALIAS),
    ],
)
async def test_unmapped_names_keep_backend_rejection(monkeypatch, mode, aliases, model):
    async with router_client(mode, aliases, monkeypatch) as (client, seen):
        response = await client.post(
            APIS[0], json={"model": model, "messages": [], "max_tokens": 8}
        )
        assert response.status_code == 404
    expected = "next" if model == ALIAS and aliases else model
    assert len(seen) == 1 and seen[0][1]["model"] == expected


@pytest.mark.parametrize(
    "model", [MODEL, "CLIENT-ALIAS", None, 1, [ALIAS], {"model": ALIAS}]
)
def test_resolver_leaves_other_values_unchanged(model):
    assert resolve_model_alias(model, {ALIAS: MODEL}) == model
