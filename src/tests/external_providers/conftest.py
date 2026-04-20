"""
Shared test helpers for external_providers tests.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from vllm_router.external_providers.models import (
    ExternalModelConfig,
    ExternalProviderConfig,
)


def make_provider_config(
    name="openai-test",
    type_="openai",
    api_base="https://api.openai.com",
    models=None,
    api_key_env_var=None,
    timeout=10.0,
    max_retries=3,
    custom_headers=None,
) -> ExternalProviderConfig:
    return ExternalProviderConfig(
        name=name,
        type=type_,
        api_base=api_base,
        models=models if models is not None else [ExternalModelConfig(id="gpt-4o")],
        api_key_env_var=api_key_env_var,
        timeout=timeout,
        max_retries=max_retries,
        custom_headers=custom_headers if custom_headers is not None else {},
    )


def make_mock_response(status: int = 200, json_data=None, headers=None) -> MagicMock:
    """Return a MagicMock usable as an async context manager for aiohttp responses."""
    resp = MagicMock()
    resp.status = status
    resp.headers = headers or {}
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def make_mock_session(*, get=None, post=None) -> MagicMock:
    """Return a MagicMock ClientSession with optional canned GET / POST responses."""
    session = MagicMock()
    session.closed = False
    if get is not None:
        session.get.return_value = get
    if post is not None:
        session.post.return_value = post
    return session


@contextmanager
def mock_get_session(provider, session):
    """Patch provider._get_session to return *session* for the duration of the block."""
    with patch.object(provider, "_get_session", AsyncMock(return_value=session)):
        yield
