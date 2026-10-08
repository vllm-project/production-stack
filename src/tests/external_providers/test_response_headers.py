import json
import socket
from types import SimpleNamespace

import pytest
from aiohttp import web
from fastapi import BackgroundTasks

from vllm_router.external_providers.models import (
    ExternalModelConfig,
    ExternalProviderConfig,
)
from vllm_router.external_providers.registry import ExternalProviderManager
from vllm_router.services.request_service.request import (
    process_external_provider_request,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize(
    "provider_request_id_header", [None, "X-Request-Id", "x-request-id", "X-ReQuEsT-Id"]
)
async def test_external_provider_response_headers_match_forwarded_body(
    monkeypatch, stream, compressed, provider_request_id_header
):
    """Forward decoded provider bodies with valid downstream response headers."""
    payload = {"choices": [{"message": {"content": "hello from the provider"}}]}
    body = (
        b'data: {"choices": []}\n\ndata: [DONE]\n\n'
        if stream
        else json.dumps(payload, indent=2).encode()
    )

    async def upstream_handler(request):
        assert (await request.json())["stream"] is stream
        headers = {"X-Provider-Trace": "provider-trace"}
        if provider_request_id_header:
            headers[provider_request_id_header] = "provider-request"
        response = web.Response(
            body=body,
            content_type="text/event-stream" if stream else "application/json",
            headers=headers,
        )
        if compressed:
            response.enable_compression(force=web.ContentCoding.gzip)
        return response

    upstream = web.Application()
    upstream.router.add_post("/v1/chat/completions", upstream_handler)
    runner = web.AppRunner(upstream)
    await runner.setup()
    registry = ExternalProviderManager()
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")

    upstream_socket = socket.socket()
    try:
        upstream_socket.bind(("127.0.0.1", 0))
        address, port = upstream_socket.getsockname()
        await web.SockSite(runner, upstream_socket).start()
        registry.register(
            ExternalProviderConfig(
                name="fixture-provider",
                type="openai",
                api_base=f"http://{address}:{port}",
                models=[ExternalModelConfig(id="fixture-model")],
            )
        )
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(external_provider_registry=registry)
            )
        )

        response = await process_external_provider_request(
            request,
            "/v1/chat/completions",
            {"model": "fixture-model", "stream": stream},
            "router-request",
            BackgroundTasks(),
        )

        assert response.headers["x-provider-trace"] == "provider-trace"
        assert response.headers.getlist("x-request-id") == ["router-request"]
        if stream:
            assert "content-length" not in response.headers
            assert response.headers["content-type"].startswith("text/event-stream")
            assert b"".join([chunk async for chunk in response.body_iterator]) == body
        else:
            assert int(response.headers["content-length"]) == len(response.body)
            assert json.loads(response.body) == payload
        for header in (
            "content-encoding",
            "transfer-encoding",
            "connection",
            "server",
        ):
            assert header not in response.headers

    finally:
        try:
            await registry.close()
        finally:
            try:
                await runner.cleanup()
            finally:
                upstream_socket.close()
