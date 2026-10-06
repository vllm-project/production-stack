"""Models without prefill/decode pods behind the orchestrated P/D router."""

import asyncio
import json
from types import SimpleNamespace
from unittest import mock

from fastapi import BackgroundTasks

import vllm_router.services.request_service.request as request_module
from vllm_router.routers.routing_logic import DisaggregatedPrefillOrchestratedRouter
from vllm_router.stats.request_stats import RequestStatsMonitor
from vllm_router.utils import SingletonABCMeta

PLAIN = [
    SimpleNamespace(
        url=u, model_label="plain", model_names=["plain-model"], sleep=False, Id=u
    )
    for u in ("http://plain-0:8000", "http://plain-1:8000")
]
PD = [
    SimpleNamespace(
        url="http://pd-prefill:8000",
        model_label="prefill",
        model_names=["pd-model"],
        sleep=False,
        Id="p",
    ),
    SimpleNamespace(
        url="http://pd-decode:8000",
        model_label="decode",
        model_names=["pd-model"],
        sleep=False,
        Id="d",
    ),
]


def _router(labels_as_string=False):
    SingletonABCMeta._instances.pop(DisaggregatedPrefillOrchestratedRouter, None)
    if labels_as_string:
        router = DisaggregatedPrefillOrchestratedRouter("prefill", "decode")
    else:
        router = DisaggregatedPrefillOrchestratedRouter(["prefill"], ["decode"])
    router.max_instance_failover_reroute_attempts = 0  # set by initialize_routing_logic
    return router


def _is_pd_model(body, endpoints, labels_as_string=False):
    async def req_json():
        return body

    discovery = SimpleNamespace(get_endpoint_info=lambda: endpoints)
    with mock.patch.object(request_module, "get_service_discovery", lambda: discovery):
        return asyncio.run(
            request_module.is_pd_model(
                SimpleNamespace(json=req_json), _router(labels_as_string)
            )
        )


def test_is_pd_model():
    endpoints = PLAIN + PD
    assert _is_pd_model({"model": "pd-model"}, endpoints)
    assert not _is_pd_model({"model": "plain-model"}, endpoints)
    assert not _is_pd_model({"model": "plain-model"}, endpoints, labels_as_string=True)
    # Unknown or missing model: the orchestrated flow answers as before.
    assert _is_pd_model({"model": "nope"}, endpoints)
    assert _is_pd_model({}, endpoints)


def test_route_request_plain_model_least_busy_pod():
    stats = {
        PLAIN[0].url: SimpleNamespace(in_prefill_requests=2, in_decoding_requests=1),
        PLAIN[1].url: SimpleNamespace(in_prefill_requests=0, in_decoding_requests=1),
    }
    url = asyncio.run(_router().route_request(PLAIN, {}, stats, None, {}))
    assert url == PLAIN[1].url


def test_route_request_pd_model_unchanged():
    url = asyncio.run(_router().route_request(PD, {}, {}, None, {}))
    assert url == PD[0].url


def test_general_path_end_to_end():
    # Before: the plain model went into the orchestrated flow (503 "no prefill
    # endpoints"), and route_request was called without await/request_json.
    sent = []

    class Response:
        status = 200
        headers = {"content-type": "application/json"}

        class content:
            @staticmethod
            async def iter_any():
                yield b'{"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}'

    class Context:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *args):
            return False

    class Client:
        def request(self, method, url, headers=None, data=None, timeout=None):
            sent.append(url)
            return Context()

    monitor = RequestStatsMonitor.__new__(RequestStatsMonitor)
    RequestStatsMonitor.__init__(monitor, 60)
    state = SimpleNamespace(
        router=_router(),
        request_stats_monitor=monitor,
        otel_enabled=False,
        callbacks=None,
        semantic_cache_available=False,
        aiohttp_client_wrapper=lambda: Client(),
        engine_stats_scraper=SimpleNamespace(get_engine_stats=lambda: {}),
    )
    body = {
        "model": "plain-model",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 4,
    }

    async def req_body():
        return json.dumps(body).encode()

    async def req_json():
        return dict(body)

    request = SimpleNamespace(
        headers={"X-Request-Id": "g1"},
        method="POST",
        query_params={},
        url="http://router/v1/chat/completions",
        app=SimpleNamespace(state=state),
        body=req_body,
        json=req_json,
    )
    discovery = SimpleNamespace(get_endpoint_info=lambda: PLAIN + PD)

    async def run():
        with mock.patch.object(
            request_module, "get_service_discovery", lambda: discovery
        ):
            response = await request_module.route_general_request(
                request, "/v1/chat/completions", BackgroundTasks()
            )
            data = b""
            async for chunk in response.body_iterator:
                data += chunk
            return response.status_code, data

    status, data = asyncio.run(run())
    assert status == 200, data
    assert len(sent) == 1 and sent[0].endswith("/v1/chat/completions")
    assert sent[0].startswith("http://plain-")
