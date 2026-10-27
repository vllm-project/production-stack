import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

from vllm_router.services.request_service.request import (
    route_disaggregated_prefill_request,
    route_general_request,
    route_general_transcriptions,
    route_orchestrated_disaggregated_request,
)

REQUEST_ID = "test-request-id"


# Build a minimal request with only the attributes needed for JSON validation.
def _json_request(body: bytes):
    return SimpleNamespace(
        headers={"X-Request-Id": REQUEST_ID},
        query_params={},
        app=SimpleNamespace(
            state=SimpleNamespace(
                router=object(),
                otel_enabled=False,
                callbacks=None,
            )
        ),
        body=AsyncMock(return_value=body),
    )


@pytest.mark.parametrize(
    "body",
    [
        b'{"model":"test-model"',
        b"\xff",
        b"[]",
        b"[" * 2_000 + b"]" * 2_000,
    ],
)
@pytest.mark.asyncio
async def test_general_request_rejects_invalid_json_body(body):
    response = await route_general_request(
        _json_request(body), "/v1/completions", BackgroundTasks()
    )

    assert response.status_code == 400
    assert json.loads(response.body)["error"]
    assert response.headers["X-Request-Id"] == REQUEST_ID


# Build a real Starlette request, so that reading the body behaves as in the router.
def _starlette_request(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/completions",
        "query_string": b"",
        "headers": [(b"x-request-id", REQUEST_ID.encode())],
        "app": SimpleNamespace(state=SimpleNamespace()),
    }
    return Request(scope, receive)


@pytest.mark.parametrize(
    "route",
    [route_disaggregated_prefill_request, route_orchestrated_disaggregated_request],
)
@pytest.mark.parametrize(
    "body",
    [
        b'{"model":"test-model"',
        b"\xff",
        b"[]",
        b"[" * 2_000 + b"]" * 2_000,
    ],
)
@pytest.mark.asyncio
async def test_disaggregated_request_rejects_invalid_json_body(route, body):
    response = await route(
        _starlette_request(body), "/v1/completions", BackgroundTasks()
    )

    assert response.status_code == 400
    assert json.loads(response.body)["error"]
    assert response.headers["X-Request-Id"] == REQUEST_ID


@pytest.mark.asyncio
async def test_transcription_rejects_non_numeric_temperature():
    request = SimpleNamespace(
        headers={"X-Request-Id": REQUEST_ID},
        form=AsyncMock(
            return_value={
                "file": object(),
                "model": "whisper-model",
                "temperature": "not-a-number",
            }
        ),
    )

    response = await route_general_transcriptions(
        request, "/v1/audio/transcriptions", BackgroundTasks()
    )

    assert response.status_code == 400
    assert json.loads(response.body) == {"error": "Invalid multipart/form-data request"}
    assert response.headers["X-Request-Id"] == REQUEST_ID
