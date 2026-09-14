import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from vllm_router.routers.routing_logic import (
    DisaggregatedPrefillOrchestratedRouter,
    DisaggregatedPrefillRouter,
    cleanup_routing_logic,
)
from vllm_router.services.request_service.request import (
    route_disaggregated_prefill_request,
    route_orchestrated_disaggregated_request,
)


class AwaitableResponse:
    def __init__(self, *, json_data=None, body=b"{}"):
        self.status = 200
        self._json_data = json_data or {}
        self._body = body
        self.content = SimpleNamespace(iter_any=self._iter_any)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def __await__(self):
        async def resolve():
            return self

        return resolve().__await__()

    async def json(self):
        return self._json_data

    async def read(self):
        return self._body

    async def text(self):
        return self._body.decode()

    async def _iter_any(self):
        yield self._body

    def release(self):
        pass


@pytest.mark.asyncio
async def test_orchestrated_prefill_and_decode_dispatches_are_each_counted_once():
    cleanup_routing_logic()
    router = DisaggregatedPrefillOrchestratedRouter(["prefill"], ["decode"])
    endpoints = [
        SimpleNamespace(
            url="http://prefill.internal:8000",
            model_label="prefill",
            Id="prefill-id",
        ),
        SimpleNamespace(
            url="http://decode.internal:8000",
            model_label="decode",
            Id="decode-id",
        ),
    ]
    responses = [
        AwaitableResponse(json_data={"kv_transfer_params": {}}),
        AwaitableResponse(body=json.dumps({"ok": True}).encode()),
    ]
    client = MagicMock()
    client.post.side_effect = responses

    request = MagicMock()
    request.headers = {}
    request.json = AsyncMock(return_value={"model": "test-model", "stream": False})
    request.app.state.router = router
    request.app.state.aiohttp_client_wrapper = MagicMock(return_value=client)

    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = endpoints

    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=service_discovery,
        ),
        patch(
            "vllm_router.services.request_service.request.record_routing_decision"
        ) as metric_mock,
    ):
        response = await route_orchestrated_disaggregated_request(
            request, "/v1/chat/completions", MagicMock()
        )

    assert response.status_code == 200
    assert metric_mock.call_args_list == [
        call(
            algorithm="disaggregated_prefill_orchestrated",
            decision="primary",
            reason="prefill",
        ),
        call(
            algorithm="disaggregated_prefill_orchestrated",
            decision="primary",
            reason="decode",
        ),
    ]
    assert "http://" not in str(metric_mock.call_args_list)
    cleanup_routing_logic()


@pytest.mark.asyncio
async def test_fixed_prefill_and_decode_dispatches_are_each_counted_once():
    cleanup_routing_logic()
    router = DisaggregatedPrefillRouter(["prefill"], ["decode"])
    endpoints = [
        SimpleNamespace(
            url="http://fixed-prefill.internal:8000",
            model_label="prefill",
            Id="fixed-prefill-id",
        ),
        SimpleNamespace(
            url="http://fixed-decode.internal:8000",
            model_label="decode",
            Id="fixed-decode-id",
        ),
    ]
    request = MagicMock()
    request.headers = {}
    request.json = AsyncMock(return_value={"model": "test-model", "stream": True})
    request.app.state.router = router
    request.app.state.prefill_client = SimpleNamespace(
        _base_url="http://fixed-prefill.internal:8000"
    )
    request.app.state.decode_client = SimpleNamespace(
        _base_url="http://fixed-decode.internal:8000"
    )

    service_discovery = MagicMock()
    service_discovery.get_endpoint_info.return_value = endpoints

    async def decode_stream(*_args, **_kwargs):
        yield b"done"

    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=service_discovery,
        ),
        patch(
            "vllm_router.services.request_service.request.send_request_to_prefiller",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "vllm_router.services.request_service.request.send_request_to_decode",
            side_effect=decode_stream,
        ),
        patch(
            "vllm_router.services.request_service.request.record_routing_decision"
        ) as metric_mock,
    ):
        response = await route_disaggregated_prefill_request(
            request, "/v1/chat/completions", MagicMock()
        )
        chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == [b"done"]
    assert metric_mock.call_args_list == [
        call(
            algorithm="disaggregated_prefill",
            decision="primary",
            reason="prefill",
        ),
        call(
            algorithm="disaggregated_prefill",
            decision="primary",
            reason="decode",
        ),
    ]
    cleanup_routing_logic()
