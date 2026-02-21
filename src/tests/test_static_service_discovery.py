import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from fastapi import FastAPI

from vllm_router.service_discovery import StaticServiceDiscovery


def test_init_when_static_backend_health_checks_calls_start_health_checks(
    mock_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_health_check_mock = MagicMock()
    monkeypatch.setattr(
        "vllm_router.service_discovery.StaticServiceDiscovery.start_health_check_task",
        start_health_check_mock,
    )
    discovery_instance = StaticServiceDiscovery(
        mock_app,
        [],
        [],
        None,
        None,
        None,
        static_backend_health_checks=True,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    discovery_instance.start_health_check_task.assert_called_once()


def test_init_when_endpoint_health_check_disabled_does_not_call_start_health_checks(
    mock_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_health_check_mock = MagicMock()
    monkeypatch.setattr(
        "vllm_router.service_discovery.StaticServiceDiscovery.start_health_check_task",
        start_health_check_mock,
    )
    discovery_instance = StaticServiceDiscovery(
        mock_app,
        [],
        [],
        None,
        None,
        None,
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    discovery_instance.start_health_check_task.assert_not_called()


@pytest.mark.asyncio
async def test_get_unhealthy_endpoint_hashes_when_only_healthy_models_exist_does_not_return_unhealthy_endpoint_hashes(
    make_mock_engine, mock_app
) -> None:
    mock_response = AsyncMock(return_value=web.json_response(status=200))
    base_url = await make_mock_engine({"/v1/chat/completions": mock_response})

    discovery_instance = StaticServiceDiscovery(
        mock_app,
        [base_url],
        ["llama3"],
        None,
        None,
        ["chat"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert await discovery_instance.get_unhealthy_endpoint_hashes() == []


@pytest.mark.asyncio
async def test_get_unhealthy_endpoint_hashes_when_unhealthy_model_exist_returns_unhealthy_endpoint_hash(
    make_mock_engine,
    mock_app,
) -> None:
    mock_response = AsyncMock(return_value=web.json_response(status=500))
    base_url = await make_mock_engine({"/v1/chat/completions": mock_response})
    expected_hash = hashlib.md5(f"{base_url}llama3".encode()).hexdigest()

    discovery_instance = StaticServiceDiscovery(
        mock_app,
        [base_url],
        ["llama3"],
        None,
        None,
        ["chat"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert await discovery_instance.get_unhealthy_endpoint_hashes() == [expected_hash]


@pytest.mark.asyncio
async def test_get_unhealthy_endpoint_hashes_when_healthy_and_unhealthy_models_exist_returns_only_unhealthy_endpoint_hash(
    make_mock_engine,
    mock_app,
) -> None:
    unhealthy_model = "bge-m3"
    mock_response = AsyncMock(return_value=web.json_response(status=500))

    async def mock_mixed_chat_response(request: web.Request) -> web.Response:
        data = await request.json()
        status = 500 if data.get("model") == unhealthy_model else 200
        return web.json_response(status=status)

    base_url = await make_mock_engine(
        {
            "/v1/chat/completions": mock_mixed_chat_response,
            "/v1/embeddings": mock_response,
        }
    )
    expected_hash = hashlib.md5(f"{base_url}{unhealthy_model}".encode()).hexdigest()

    discovery_instance = StaticServiceDiscovery(
        mock_app,
        [base_url, base_url],
        ["llama3", unhealthy_model],
        None,
        None,
        ["chat", "embeddings"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    assert await discovery_instance.get_unhealthy_endpoint_hashes() == [expected_hash]


def test_get_endpoint_info_when_model_endpoint_hash_is_in_unhealthy_endpoint_does_not_return_endpoint(
    mock_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unhealthy_model = "mistral"

    def mock_get_model_endpoint_hash(url: str, model: str) -> str:
        return "some-hash" if model == unhealthy_model else "other-hash"

    discovery_instance = StaticServiceDiscovery(
        mock_app,
        ["http://localhost.com", "http://10.123.112.412"],
        ["llama3", unhealthy_model],
        None,
        None,
        ["chat", "chat"],
        static_backend_health_checks=False,
        prefill_model_labels=None,
        decode_model_labels=None,
    )
    discovery_instance.unhealthy_endpoint_hashes = ["some-hash"]
    monkeypatch.setattr(
        discovery_instance, "get_model_endpoint_hash", mock_get_model_endpoint_hash
    )
    assert len(discovery_instance.get_endpoint_info()) == 1
    assert "llama3" in discovery_instance.get_endpoint_info()[0].model_names
