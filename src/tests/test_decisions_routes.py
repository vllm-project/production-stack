from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from vllm_router.routers import main_router as main_router_module


@pytest.mark.parametrize("path", ["/v1/systemone", "/v1/decisions"])
def test_decisions_routes_forward_to_general_request(monkeypatch, path):
    mock = AsyncMock(return_value=JSONResponse({"ok": True}))
    monkeypatch.setattr(main_router_module, "route_general_request", mock)
    app = FastAPI()
    app.include_router(main_router_module.main_router)

    response = TestClient(app).post(path, json={"model": "Qwen/Qwen3-0.6B"})

    assert response.status_code == 200
    assert mock.await_args.args[1] == path
