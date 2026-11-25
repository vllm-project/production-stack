"""Failover in the orchestrated P/D flow: a prefill or decode endpoint that fails
before response headers is replaced by another endpoint of the same role."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from fastapi import BackgroundTasks

from vllm_router.routers.routing_logic import (
    RoutingLogic,
    cleanup_routing_logic,
    initialize_routing_logic,
)
from vllm_router.services.request_service.request import (
    route_orchestrated_disaggregated_request,
)

ENDPOINT = "/v1/chat/completions"
FIRST_CHUNK = b'data: {"id": "1"}\n\n'
LAST_CHUNK = b"data: [DONE]\n\n"


class Pod:
    """A prefill or decode engine. `behavior` is "ok", an HTTP status to answer
    with, "refuse" (nothing listens on the port) or "cut" (the response starts,
    then the connection drops once `first_chunk_read` is set)."""

    def __init__(self, role):
        self.role = role
        self.behavior = "ok"
        self.requests = []
        self.first_chunk_read = asyncio.Event()
        self.url = None
        self.server = None

    async def start(self):
        app = web.Application()
        app.router.add_post(ENDPOINT, self.handle)
        self.server = TestServer(app)
        await self.server.start_server()
        self.url = f"http://127.0.0.1:{self.server.port}"

    async def handle(self, request):
        body = await request.json()
        self.requests.append(body)
        if isinstance(self.behavior, int):
            return web.json_response(
                {"error": f"{self.role} unavailable"}, status=self.behavior
            )
        if self.role == "prefill":
            return web.json_response(
                {"kv_transfer_params": {"remote_engine_id": self.url}}
            )
        if not body.get("stream"):
            return web.json_response({"served_by": self.url})
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(FIRST_CHUNK)
        if self.behavior == "cut":
            await self.first_chunk_read.wait()
            request.transport.abort()
            return response
        await response.write(LAST_CHUNK)
        return response

    def endpoint_info(self):
        return SimpleNamespace(
            url=self.url,
            model_label=self.role,
            model_names=["test-model"],
            sleep=False,
        )


class Cluster:
    """Prefill and decode pods behind an orchestrated P/D router."""

    def __init__(self, router, prefill, decode):
        self.router = router
        self.prefill = prefill
        self.decode = decode
        self.client = aiohttp.ClientSession()

    async def request(self, stream=False):
        """Send one request through the orchestrated flow."""
        request = MagicMock()
        request.headers = {}
        request.json = AsyncMock(
            return_value={"model": "test-model", "messages": [], "stream": stream}
        )
        request.app.state.router = self.router
        request.app.state.aiohttp_client_wrapper = lambda: self.client

        service_discovery = MagicMock()
        service_discovery.get_endpoint_info.return_value = [
            pod.endpoint_info() for pod in self.prefill + self.decode
        ]
        with patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=service_discovery,
        ):
            return await route_orchestrated_disaggregated_request(
                request, ENDPOINT, BackgroundTasks()
            )


@pytest.fixture
async def cluster():
    """Start a cluster: `prefill` and `decode` list the behavior of each pod of
    that role, in the order the router's round-robin picks them."""
    cleanup_routing_logic()
    clusters = []

    async def _start_pods(role, behaviors):
        pods = [Pod(role) for _ in behaviors]
        for pod in pods:
            await pod.start()
        # The router's round-robin starts with the lowest URL.
        pods.sort(key=lambda pod: pod.url)
        for pod, behavior in zip(pods, behaviors):
            pod.behavior = behavior
            if behavior == "refuse":
                await pod.server.close()
        return pods

    async def _start(prefill, decode, attempts=1, **router_kwargs):
        router = initialize_routing_logic(
            RoutingLogic.DISAGGREGATED_PREFILL_ORCHESTRATED,
            prefill_model_labels=["prefill"],
            decode_model_labels=["decode"],
            max_instance_failover_reroute_attempts=attempts,
            **router_kwargs,
        )
        clusters.append(
            Cluster(
                router,
                await _start_pods("prefill", prefill),
                await _start_pods("decode", decode),
            )
        )
        return clusters[-1]

    yield _start

    for started in clusters:
        await started.client.close()
        for pod in started.prefill + started.decode:
            await pod.server.close()
    cleanup_routing_logic()


@pytest.mark.parametrize("failure", [503, "refuse"])
async def test_prefill_failure_moves_to_another_prefill_endpoint(cluster, failure):
    pods = await cluster(prefill=[failure, "ok"], decode=["ok"])
    response = await pods.request()

    assert response.status_code == 200
    assert len(pods.prefill[1].requests) == 1
    # The decode request carries the KV parameters of the prefill that succeeded.
    assert pods.decode[0].requests[0]["kv_transfer_params"] == {
        "remote_engine_id": pods.prefill[1].url,
        "remote_host": "127.0.0.1",
    }


async def test_prefill_client_error_is_not_retried(cluster):
    pods = await cluster(prefill=[400, "ok"], decode=["ok"])
    response = await pods.request()

    assert response.status_code == 400
    assert pods.prefill[1].requests == []
    assert pods.decode[0].requests == []


@pytest.mark.parametrize("failure", [503, "refuse"])
async def test_streaming_decode_failure_moves_to_another_decode_endpoint(
    cluster, failure
):
    pods = await cluster(prefill=["ok"], decode=[failure, "ok"])
    response = await pods.request(stream=True)

    assert response.status_code == 200
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == FIRST_CHUNK + LAST_CHUNK
    assert len(pods.prefill[0].requests) == 1
    assert pods.decode[1].requests[0]["kv_transfer_params"]["remote_engine_id"] == (
        pods.prefill[0].url
    )


async def test_non_streaming_decode_retries_a_refused_connection(cluster):
    pods = await cluster(prefill=["ok"], decode=["refuse", "ok"])
    response = await pods.request()

    assert response.status_code == 200
    assert json.loads(response.body) == {"served_by": pods.decode[1].url}


async def test_non_streaming_decode_server_error_is_not_retried(cluster):
    # The response headers of a non-streaming request come after generation:
    # the failed endpoint may already have pulled the KV cache.
    pods = await cluster(prefill=["ok"], decode=[503, "ok"])
    response = await pods.request()

    assert response.status_code == 503
    assert pods.decode[1].requests == []


async def test_no_retry_once_the_response_has_started(cluster):
    pods = await cluster(prefill=["ok"], decode=["cut", "ok"])
    response = await pods.request(stream=True)

    assert response.status_code == 200
    received = []
    with pytest.raises(aiohttp.ClientError):
        async for chunk in response.body_iterator:
            received.append(chunk)
            pods.decode[0].first_chunk_read.set()
    assert received == [FIRST_CHUNK]
    assert pods.decode[1].requests == []


async def test_error_is_returned_when_attempts_are_exhausted(cluster):
    pods = await cluster(prefill=[503, 503, 503], decode=["ok"])
    response = await pods.request()

    assert response.status_code == 503
    assert b"Prefill failed" in response.body
    # One reroute attempt: two of the three prefill endpoints were tried.
    assert sorted(len(pod.requests) for pod in pods.prefill) == [0, 1, 1]
    assert pods.decode[0].requests == []


async def test_connection_error_is_returned_when_every_endpoint_failed(cluster):
    pods = await cluster(prefill=["refuse", "refuse"], decode=["ok"], attempts=5)
    response = await pods.request()

    assert response.status_code == 503
    assert b"HTTP error" in response.body
    assert pods.decode[0].requests == []


async def test_no_failover_by_default(cluster):
    pods = await cluster(prefill=[503, "ok"], decode=["ok"], attempts=0)
    response = await pods.request()

    assert response.status_code == 503
    assert pods.prefill[1].requests == []


async def test_failing_prefill_endpoint_is_skipped_after_threshold(cluster):
    pods = await cluster(
        prefill=[503, "ok"], decode=["ok"], pd_endpoint_failure_threshold=2
    )

    statuses = [(await pods.request()).status_code for _ in range(6)]

    assert statuses == [200] * 6
    # Round-robin offered the failing endpoint twice; after that it is skipped.
    assert len(pods.prefill[0].requests) == 2
    assert len(pods.prefill[1].requests) == 6


async def test_failing_decode_endpoint_is_skipped_after_threshold(cluster):
    pods = await cluster(
        prefill=["ok"], decode=["refuse", "ok"], pd_endpoint_failure_threshold=1
    )

    statuses = [(await pods.request()).status_code for _ in range(4)]

    assert statuses == [200] * 4
    assert pods.router.circuit_breaker.available(
        [pod.endpoint_info() for pod in pods.decode]
    ) == [pods.decode[1].endpoint_info()]


async def test_circuit_breaker_works_without_failover(cluster):
    pods = await cluster(
        prefill=[503, "ok"],
        decode=["ok"],
        attempts=0,
        pd_endpoint_failure_threshold=1,
    )

    statuses = [(await pods.request()).status_code for _ in range(4)]

    assert statuses == [503, 200, 200, 200]
    assert len(pods.prefill[0].requests) == 1


async def test_client_error_does_not_open_the_circuit_breaker(cluster):
    pods = await cluster(
        prefill=[400, "ok"], decode=["ok"], pd_endpoint_failure_threshold=1
    )

    statuses = [(await pods.request()).status_code for _ in range(4)]

    assert statuses == [400, 200, 400, 200]
