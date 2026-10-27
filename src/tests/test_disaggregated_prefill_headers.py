"""The P/D routes forward the client's headers, Authorization
included, to the prefill and decode engines, like the other proxy paths."""

from types import SimpleNamespace

import pytest

from vllm_router.services.request_service import request as request_module


class _Request:
    def __init__(self, headers):
        self.headers = headers
        client = SimpleNamespace(_base_url="http://engine")
        self.app = SimpleNamespace(
            state=SimpleNamespace(prefill_client=client, decode_client=client)
        )

    async def json(self):
        return {"model": "m", "prompt": "hi", "max_tokens": 8}


async def _route(monkeypatch, headers):
    seen = []

    async def fake_prefiller(client, endpoint, req_data, backend_headers):
        seen.append(("prefill", backend_headers.get("Authorization")))

    async def fake_decode(client, endpoint, req_data, backend_headers):
        seen.append(("decode", backend_headers.get("Authorization")))
        yield b"{}"

    monkeypatch.setattr(request_module, "send_request_to_prefiller", fake_prefiller)
    monkeypatch.setattr(request_module, "send_request_to_decode", fake_decode)
    response = await request_module.route_disaggregated_prefill_request(
        _Request(headers), "/v1/completions", None
    )
    async for _ in response.body_iterator:
        pass
    return seen


@pytest.mark.asyncio
async def test_client_authorization_reaches_both_engines(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = await _route(monkeypatch, {"Authorization": "Bearer client-key"})
    assert seen == [("prefill", "Bearer client-key"), ("decode", "Bearer client-key")]


@pytest.mark.asyncio
async def test_router_key_applies_when_client_sends_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "router-key")
    seen = await _route(monkeypatch, {})
    assert seen == [("prefill", "Bearer router-key"), ("decode", "Bearer router-key")]


@pytest.mark.asyncio
async def test_no_key_anywhere_sends_no_authorization(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = await _route(monkeypatch, {})
    assert seen == [("prefill", None), ("decode", None)]


def test_pd_headers_leave_content_type_to_the_json_body(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "router-key")
    headers = request_module._build_pd_backend_headers(
        _Request({"Content-Type": "text/plain", "X-Request-Id": "client"}), "rid"
    )
    assert headers == {"X-Request-Id": "rid", "Authorization": "Bearer router-key"}
