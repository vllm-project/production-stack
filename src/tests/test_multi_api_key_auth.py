from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from vllm_router.auth import _parse_api_keys, get_allowed_api_keys, verify_api_key

# ---------------------------------------------------------------------------
# _parse_api_keys
# ---------------------------------------------------------------------------


def test_parse_single_key():
    assert _parse_api_keys("key1") == {"key1"}


def test_parse_comma_separated_keys():
    assert _parse_api_keys("key1,key2,key3") == {"key1", "key2", "key3"}


def test_parse_strips_whitespace():
    assert _parse_api_keys("key1, key2 , key3") == {"key1", "key2", "key3"}


def test_parse_ignores_empty_segments():
    assert _parse_api_keys("key1,,key2") == {"key1", "key2"}
    assert _parse_api_keys(",key1,") == {"key1"}


def test_parse_empty_string_returns_empty_set():
    assert _parse_api_keys("") == frozenset()


def test_parse_whitespace_only_returns_empty_set():
    assert _parse_api_keys("  ,  ") == frozenset()


# ---------------------------------------------------------------------------
# get_allowed_api_keys — reads from environment
# ---------------------------------------------------------------------------


def test_get_allowed_api_keys_no_env_var(monkeypatch):
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    assert get_allowed_api_keys() == frozenset()


def test_get_allowed_api_keys_single(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "secret")
    assert get_allowed_api_keys() == {"secret"}


def test_get_allowed_api_keys_multiple(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "key1,key2,key3")
    assert get_allowed_api_keys() == {"key1", "key2", "key3"}


def test_get_allowed_api_keys_trims_spaces(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", " key1 , key2 ")
    assert get_allowed_api_keys() == {"key1", "key2"}


# ---------------------------------------------------------------------------
# verify_api_key dependency
# ---------------------------------------------------------------------------


def _make_request(auth_header: str | None = None) -> MagicMock:
    request = MagicMock()
    headers = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    request.headers = headers
    return request


@pytest.mark.anyio
async def test_verify_no_keys_configured_allows_all(monkeypatch):
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    request = _make_request()
    await verify_api_key(request)  # must not raise


@pytest.mark.anyio
async def test_verify_valid_single_key(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "secret")
    request = _make_request("Bearer secret")
    await verify_api_key(request)  # must not raise


@pytest.mark.anyio
async def test_verify_valid_key_among_multiple(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "key1,key2,key3")
    for key in ("key1", "key2", "key3"):
        request = _make_request(f"Bearer {key}")
        await verify_api_key(request)  # must not raise


@pytest.mark.anyio
async def test_verify_invalid_key_raises_401(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "key1,key2")
    request = _make_request("Bearer wrong-key")
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(request)
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_verify_missing_auth_header_raises_401(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "secret")
    request = _make_request()  # no Authorization header
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(request)
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_verify_non_bearer_scheme_raises_401(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "secret")
    request = _make_request("Basic secret")
    with pytest.raises(HTTPException) as exc_info:
        await verify_api_key(request)
    assert exc_info.value.status_code == 401


@pytest.mark.anyio
async def test_verify_extra_whitespace_in_env_key(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", " key1 , key2 ")
    request = _make_request("Bearer key1")
    await verify_api_key(request)  # must not raise
