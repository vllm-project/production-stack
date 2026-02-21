from typing import Any, AsyncGenerator, Callable
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import web
from fastapi import FastAPI


@pytest.fixture
async def mock_app() -> AsyncGenerator[FastAPI]:
    mock_app = MagicMock()
    async with aiohttp.ClientSession() as session:
        mock_app.state.aiohttp_client_wrapper = MagicMock(return_value=session)
        yield mock_app


@pytest.fixture
async def make_mock_engine(aiohttp_client: Any) -> Callable[[dict[str, Callable]], str]:
    async def _make_mock_engine(routes: dict[str, Callable]) -> str:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_post(path, handler)

        client = await aiohttp_client(app)
        return str(client.make_url(""))

    return _make_mock_engine
