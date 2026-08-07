# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Regression tests for https://github.com/vllm-project/production-stack/issues/1016

KvawareRouter.route_request performed blocking I/O (tokenizer download,
fallback /tokenize HTTP POST) directly on the uvicorn event loop, starving
/health probes and CrashLooping the router under sustained traffic.
"""

import asyncio
import time
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from uhashring import HashRing

from vllm_router.routers import routing_logic
from vllm_router.routers.routing_logic import KvawareRouter


@pytest.fixture(autouse=True)
def stub_lmcache_names(monkeypatch):
    """lmcache is an optional runtime dep; provide the message names the
    router constructs (they only reach the mocked query_manager)."""
    monkeypatch.setattr(routing_logic, "LookupMsg", MagicMock(), raising=False)
    monkeypatch.setattr(routing_logic, "QueryInstMsg", MagicMock(), raising=False)


class EndpointInfo:
    def __init__(self, url: str, model_names=None):
        self.url = url
        self.model_names = model_names or ["test-model"]


class Request:
    def __init__(self, headers: Dict[str, str], body: Dict[str, Any] = None):
        self.headers = headers
        self.body = body


class FakeTokenizer:
    def encode(self, text):
        return [1, 2, 3]


def make_router() -> KvawareRouter:
    """KvawareRouter without __init__ (avoids LMCache controller setup)."""
    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizer = None
    router._tokenizer_load_failed = False
    router.session_key = None
    router.threshold = 2000
    router.hash_ring = HashRing()
    router.instance_id_to_ip = {}
    # No KV layout hits: fall through to the QPS/session fallback path,
    # which returns endpoints[0].url when request_stats is empty.
    router.query_manager = AsyncMock(return_value=SimpleNamespace(layout_info={}))
    return router


async def run_with_health_probe(coro, probe_interval=0.05):
    """Run coro alongside a fake /health probe; return probe ticks at coro end."""
    ticks = 0

    async def health_probe():
        nonlocal ticks
        for _ in range(20):
            ticks += 1
            await asyncio.sleep(probe_interval)

    route_task = asyncio.ensure_future(coro)
    probe_task = asyncio.ensure_future(health_probe())
    await route_task
    ticks_when_route_finished = ticks
    probe_task.cancel()
    return ticks_when_route_finished


@pytest.mark.asyncio
async def test_tokenizer_load_does_not_block_event_loop():
    """A slow tokenizer download must not freeze the event loop."""
    router = make_router()
    endpoint = EndpointInfo(url="http://engine1.com")

    with patch.object(routing_logic, "AutoTokenizer") as at:
        at.from_pretrained.side_effect = lambda name: time.sleep(0.3) or FakeTokenizer()
        ticks = await run_with_health_probe(
            router.route_request(
                [endpoint], None, {}, Request(headers={}), {"prompt": "hi"}
            )
        )

    # If the loop were blocked for the full 0.3s load, the probe could not
    # tick at all before the route finished.
    assert ticks >= 3, f"health probe starved during tokenizer load ({ticks} ticks)"


@pytest.mark.asyncio
async def test_remote_tokenize_fallback_does_not_block_event_loop():
    """The fallback /tokenize HTTP POST must not freeze the event loop."""
    router = make_router()
    endpoint = EndpointInfo(url="http://engine1.com")

    response = MagicMock()
    response.json.return_value = {"tokens": [1, 2, 3]}

    with (
        patch.object(routing_logic, "AutoTokenizer") as at,
        patch.object(routing_logic, "requests") as req,
    ):
        at.from_pretrained.side_effect = RuntimeError("huggingface.co unreachable")
        req.post.side_effect = lambda *a, **k: time.sleep(0.3) or response
        ticks = await run_with_health_probe(
            router.route_request(
                [endpoint], None, {}, Request(headers={}), {"prompt": "hi"}
            )
        )

    assert ticks >= 3, f"health probe starved during /tokenize POST ({ticks} ticks)"


@pytest.mark.asyncio
async def test_failed_tokenizer_load_is_not_retried_every_request():
    """A doomed tokenizer load (alias model name / blocked egress) must be
    cached as failed instead of re-attempted on every request."""
    router = make_router()
    endpoint = EndpointInfo(url="http://engine1.com")

    response = MagicMock()
    response.json.return_value = {"tokens": [1, 2, 3]}

    with (
        patch.object(routing_logic, "AutoTokenizer") as at,
        patch.object(routing_logic, "requests") as req,
    ):
        at.from_pretrained.side_effect = RuntimeError("huggingface.co unreachable")
        req.post.return_value = response

        for _ in range(3):
            url = await router.route_request(
                [endpoint], None, {}, Request(headers={}), {"prompt": "hi"}
            )
            assert url == endpoint.url

    assert at.from_pretrained.call_count == 1
    assert req.post.call_count == 3  # remote /tokenize fallback every time


@pytest.mark.asyncio
async def test_local_tokenizer_loaded_once_and_reused():
    """Successful local tokenization caches the tokenizer (unchanged behavior)."""
    router = make_router()
    endpoint = EndpointInfo(url="http://engine1.com")

    with (
        patch.object(routing_logic, "AutoTokenizer") as at,
        patch.object(routing_logic, "requests") as req,
    ):
        at.from_pretrained.return_value = FakeTokenizer()

        for _ in range(2):
            url = await router.route_request(
                [endpoint], None, {}, Request(headers={}), {"prompt": "hi"}
            )
            assert url == endpoint.url

    assert at.from_pretrained.call_count == 1
    req.post.assert_not_called()
