"""The orchestrated P/D flow's prefill request generates exactly one token.

The prefill request is sent with max_tokens=1; the decode request is the
client's original body. Two cases broke that:

* min_tokens > 1 was copied into the prefill request, and vLLM rejects
  min_tokens > max_tokens with a 400, so the whole request failed.
* /v1/responses ignores max_tokens (it reads max_output_tokens, default: the
  rest of the context), so the prefill generated a whole answer and returned
  kv_transfer_params for prompt + output; decode then built on KV that did not
  match its prompt.
"""

import asyncio
import copy
from types import SimpleNamespace
from unittest import mock

import pytest

import vllm_router.services.request_service.request as request_module


class _Resp:
    def __init__(self, body):
        self.status = 200
        self._body = body

    async def json(self):
        return copy.deepcopy(self._body)

    async def read(self):
        import json

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
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, copy.deepcopy(json)))
        if len(self.calls) == 1:  # prefill
            return _Call(
                _Resp(
                    {
                        "kv_transfer_params": {
                            "remote_block_ids": [1],
                            "remote_host": "x",
                        }
                    }
                )
            )
        return _Call(_Resp({"ok": True}))  # decode


def _run(endpoint, body):
    client = _Client()
    router = SimpleNamespace(
        _find_endpoints=lambda eps: (eps[:1], eps[1:]),
        select_prefill_endpoint=lambda eps: eps[0],
        select_decode_endpoint=lambda eps: eps[0],
    )
    state = SimpleNamespace(router=router, aiohttp_client_wrapper=lambda: client)
    request = SimpleNamespace(headers={}, app=SimpleNamespace(state=state))

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
    with mock.patch.object(request_module, "get_service_discovery", lambda: discovery):
        response = asyncio.run(
            request_module.route_orchestrated_disaggregated_request(
                request, endpoint, None
            )
        )
    assert response.status_code == 200
    (prefill_url, prefill), (decode_url, decode) = client.calls
    assert prefill_url.endswith(endpoint) and decode_url.endswith(endpoint)
    return prefill, decode


@pytest.mark.parametrize("max_tokens", [200, None])
def test_min_tokens_only_on_the_decode_request(max_tokens):
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "min_tokens": 200,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    prefill, decode = _run("/v1/chat/completions", body)
    assert prefill["max_tokens"] == 1
    assert "min_tokens" not in prefill
    assert decode["min_tokens"] == 200
    assert decode.get("max_tokens") == max_tokens


@pytest.mark.parametrize("max_output_tokens", [300, None])
def test_responses_prefill_generates_one_token(max_output_tokens):
    body = {"model": "m", "input": "What is the weather in Berlin?"}
    if max_output_tokens is not None:
        body["max_output_tokens"] = max_output_tokens
    prefill, decode = _run("/v1/responses", body)
    assert prefill["max_output_tokens"] == 1
    assert decode.get("max_output_tokens") == max_output_tokens
    assert "max_tokens" not in decode


def test_chat_prefill_gets_no_max_output_tokens():
    prefill, _ = _run(
        "/v1/chat/completions",
        {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 64,
        },
    )
    assert "max_output_tokens" not in prefill
