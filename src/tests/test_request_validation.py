import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

from vllm_router.services.request_service.request import (
    route_general_request,
    route_general_transcriptions,
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
