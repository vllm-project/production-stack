"""The orchestrated P/D decode request has no ten-minute total limit.

The decode request used aiohttp.ClientTimeout(total=600), so every response
still generating after ten minutes (e.g. a 60k+ token reasoning answer at
~100 tokens/s) was cut mid-stream and the client saw a truncated body. A
streaming decode now only fails after DECODE_STREAM_IDLE_TIMEOUT_S without data.
"""

import asyncio
import copy
import json
from types import SimpleNamespace
from unittest import mock

import pytest

import vllm_router.services.request_service.request as request_module


class _Content:
    async def iter_any(self):
        yield b"data: {}\n\n"


class _Resp:
    def __init__(self, body):
        self.status = 200
        self._body = body
        self.content = _Content()

    async def json(self):
        return copy.deepcopy(self._body)

    async def read(self):
        return json.dumps(self._body).encode()

    async def text(self):
        return ""

    def release(self):
        pass


class _Call:
    """client.post(...): used with `async with` (prefill) and `await` (decode)."""

    def __init__(self, resp):
        self.resp = resp

    async def __aenter__(self):
        return self.resp

    async def __aexit__(self, *exc):
        return False

    def __await__(self):
        async def get():
            return self.resp

        return get().__await__()


class _Client:
    def __init__(self):
        self.timeouts = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.timeouts.append(timeout)
        if len(self.timeouts) == 1:  # prefill
            return _Call(_Resp({"kv_transfer_params": {"remote_block_ids": [1]}}))
        return _Call(_Resp({"ok": True}))  # decode


def _run(stream):
    client = _Client()
    router = SimpleNamespace(
        _find_endpoints=lambda eps: (eps[:1], eps[1:]),
        select_prefill_endpoint=lambda eps: eps[0],
        select_decode_endpoint=lambda eps: eps[0],
    )
    state = SimpleNamespace(router=router, aiohttp_client_wrapper=lambda: client)
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=state))
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 131072,
        "stream": stream,
    }

    async def req_json():
        return copy.deepcopy(body)

    request.json = req_json
    endpoints = [
        SimpleNamespace(
            url="http://prefill:8000",
            model_label="prefill",
            model_names=["m"],
            sleep=False,
        ),
        SimpleNamespace(
            url="http://decode:8000",
            model_label="decode",
            model_names=["m"],
            sleep=False,
        ),
    ]
    discovery = SimpleNamespace(get_endpoint_info=lambda: endpoints)

    async def go():
        resp = await request_module.route_orchestrated_disaggregated_request(
            request, "/v1/chat/completions", None
        )
        if hasattr(resp, "body_iterator"):
            async for _ in resp.body_iterator:
                pass
        return resp

    with mock.patch.object(request_module, "get_service_discovery", lambda: discovery):
        response = asyncio.run(go())
    assert response.status_code == 200
    return client.timeouts


IDLE = getattr(request_module, "DECODE_STREAM_IDLE_TIMEOUT_S", 600)


@pytest.mark.parametrize("stream, idle", [(True, IDLE), (False, None)])
def test_decode_has_no_total_limit(stream, idle):
    prefill_timeout, decode_timeout = _run(stream)
    assert prefill_timeout.total == 300  # prefill unchanged
    assert decode_timeout.total is None
    assert decode_timeout.sock_read == idle
    # An unreachable decode engine still fails fast.
    assert decode_timeout.sock_connect == 30
