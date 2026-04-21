"""
Tests for src/vllm_router/external_providers/openai_provider.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from vllm_router.external_providers.base import ExternalProviderResponse
from vllm_router.external_providers.models import ExternalModelConfig
from vllm_router.external_providers.openai_provider import OpenAIProvider

from .conftest import (
    make_mock_response,
    make_mock_session,
    make_provider_config,
    mock_get_session,
)


@pytest.fixture
def openai_provider(monkeypatch) -> OpenAIProvider:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = make_provider_config(
        name="openai",
        type_="openai",
        api_base="https://api.openai.com",
        models=[ExternalModelConfig(id="gpt-4o", aliases=["gpt4o"])],
        api_key_env_var="OPENAI_API_KEY",
        max_retries=2,
    )
    return OpenAIProvider(cfg)


class TestOpenAIProviderInit:
    def test_reads_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-abc")
        provider = OpenAIProvider(
            make_provider_config(api_key_env_var="OPENAI_API_KEY")
        )
        assert provider.api_key == "sk-abc"

    def test_raises_when_openai_api_key_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIProvider(make_provider_config(api_key_env_var=None))


class TestOpenAIProviderBuildHeaders:
    def test_includes_content_type(self, openai_provider):
        assert openai_provider._build_headers()["Content-Type"] == "application/json"

    def test_includes_authorization(self, openai_provider):
        assert openai_provider._build_headers()["Authorization"] == "Bearer sk-test"

    def test_no_authorization_when_api_key_is_none(self, openai_provider):
        openai_provider.api_key = None
        assert "Authorization" not in openai_provider._build_headers()

    def test_includes_custom_headers(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        provider = OpenAIProvider(
            make_provider_config(
                api_key_env_var="OPENAI_API_KEY",
                custom_headers={"X-Custom": "value", "X-Org": "org-123"},
            )
        )
        headers = provider._build_headers()
        assert headers["X-Custom"] == "value"
        assert headers["X-Org"] == "org-123"


class TestOpenAIProviderSendRequest:
    @pytest.mark.asyncio
    async def test_standard_request_success(self, openai_provider):
        response_data = {"id": "chatcmpl-abc", "choices": []}
        session = make_mock_session(
            post=make_mock_response(
                200, response_data, {"Content-Type": "application/json"}
            )
        )
        with mock_get_session(openai_provider, session):
            result = await openai_provider.send_request(
                "/v1/chat/completions",
                {"model": "gpt-4o", "messages": []},
                stream=False,
            )

        assert result.status_code == 200
        assert result.body == response_data
        assert result.is_stream is False

    @pytest.mark.asyncio
    async def test_alias_is_resolved_in_forwarded_payload(self, openai_provider):
        captured: dict = {}

        async def fake_send(session, url, headers, payload):
            captured.update(payload)
            return ExternalProviderResponse(status_code=200, body={})

        with (
            mock_get_session(openai_provider, make_mock_session()),
            patch.object(
                openai_provider, "_send_standard_request", side_effect=fake_send
            ),
        ):
            await openai_provider.send_request(
                "/v1/chat/completions",
                {"model": "gpt4o"},  # alias → should become gpt-4o
            )

        assert captured["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_streaming_returns_stream_response(self, openai_provider):
        async def fake_stream(session, url, headers, payload):
            async def _chunks():
                yield b"data: chunk1\n"
                yield b"data: chunk2\n"

            return ExternalProviderResponse(
                status_code=200, is_stream=True, stream_iterator=_chunks()
            )

        with (
            mock_get_session(openai_provider, make_mock_session()),
            patch.object(
                openai_provider, "_send_streaming_request", side_effect=fake_stream
            ),
        ):
            result = await openai_provider.send_request(
                "/v1/chat/completions", {"model": "gpt-4o"}, stream=True
            )

        assert result.is_stream is True
        assert [c async for c in result.stream_iterator] == [
            b"data: chunk1\n",
            b"data: chunk2\n",
        ]

    @pytest.mark.asyncio
    async def test_retries_on_transient_error_then_succeeds(self, openai_provider):
        attempt = 0

        async def flaky_send(session, url, headers, payload):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise aiohttp.ClientError("timeout")
            return ExternalProviderResponse(status_code=200, body={"ok": True})

        with (
            mock_get_session(openai_provider, make_mock_session()),
            patch.object(
                openai_provider, "_send_standard_request", side_effect=flaky_send
            ),
        ):
            result = await openai_provider.send_request(
                "/v1/chat/completions", {"model": "gpt-4o"}
            )

        assert result.status_code == 200
        assert attempt == 2

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self, openai_provider):
        async def always_fail(session, url, headers, payload):
            raise aiohttp.ClientError("permanent failure")

        with (
            mock_get_session(openai_provider, make_mock_session()),
            patch.object(
                openai_provider, "_send_standard_request", side_effect=always_fail
            ),
            pytest.raises(aiohttp.ClientError),
        ):
            await openai_provider.send_request(
                "/v1/chat/completions", {"model": "gpt-4o"}
            )


class TestOpenAIProviderHealthCheck:
    @pytest.mark.parametrize("status, expected", [(200, True), (503, False)])
    @pytest.mark.asyncio
    async def test_health_check_reflects_http_status(
        self, openai_provider, status, expected
    ):
        session = make_mock_session(get=make_mock_response(status))
        with mock_get_session(openai_provider, session):
            assert await openai_provider.health_check() is expected

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_connection_error(
        self, openai_provider
    ):
        with patch.object(
            openai_provider, "_get_session", side_effect=aiohttp.ClientError("refused")
        ):
            assert await openai_provider.health_check() is False


class TestOpenAIProviderFetchAvailableModelIds:
    @pytest.mark.asyncio
    async def test_returns_model_ids_from_provider(self, openai_provider):
        resp = make_mock_response(
            200, {"data": [{"id": "gpt-4o"}, {"id": "gpt-3.5-turbo"}]}
        )
        with mock_get_session(openai_provider, make_mock_session(get=resp)):
            ids = await openai_provider.fetch_available_model_ids()
        assert ids == ["gpt-4o", "gpt-3.5-turbo"]

    @pytest.mark.parametrize("status", [401, 403, 500])
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_error_status(self, openai_provider, status):
        with mock_get_session(
            openai_provider, make_mock_session(get=make_mock_response(status))
        ):
            assert await openai_provider.fetch_available_model_ids() == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_connection_error(self, openai_provider):
        with patch.object(
            openai_provider,
            "_get_session",
            side_effect=aiohttp.ClientError("no connectivity"),
        ):
            assert await openai_provider.fetch_available_model_ids() == []


class TestOpenAIProviderClose:
    @pytest.mark.asyncio
    async def test_closes_open_session(self, openai_provider):
        session = MagicMock(closed=False)
        session.close = AsyncMock()
        openai_provider._session = session

        await openai_provider.close()

        session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_already_closed_session(self, openai_provider):
        session = MagicMock(closed=True)
        session.close = AsyncMock()
        openai_provider._session = session

        await openai_provider.close()

        session.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_error_when_session_is_none(self, openai_provider):
        await openai_provider.close()  # _session is None by default — must not raise
