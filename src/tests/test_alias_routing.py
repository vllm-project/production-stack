import json
from unittest.mock import MagicMock, patch

import pytest

from vllm_router.routers.routing_logic import RoundRobinRouter
from vllm_router.utils import AliasConfig, SingletonABCMeta


class FakeEndpointInfo:
    def __init__(self, url, model_names=None, sleep=False, Id=None):
        self.url = url
        self.model_names = model_names or ["deepseek-r1"]
        self.sleep = sleep
        self.Id = Id


ENDPOINTS = [FakeEndpointInfo(url="http://engine1")]

MOCK_HEADERS = MagicMock()
MOCK_HEADERS.items.return_value = [("content-type", "text/event-stream")]


@pytest.fixture(autouse=True)
def cleanup_singletons():
    yield
    for cls in list(SingletonABCMeta._instances.keys()):
        del SingletonABCMeta._instances[cls]


def _make_service_discovery(aliases):
    sd = MagicMock()
    sd.get_endpoint_info.return_value = ENDPOINTS
    sd.aliases = aliases
    sd.has_ever_seen_model.return_value = True
    return sd


def _make_request(body_dict, router):
    state = MagicMock()
    state.router = router
    state.engine_stats_scraper.get_engine_stats.return_value = {}
    state.request_stats_monitor.get_request_stats.return_value = {}
    state.otel_enabled = False
    state.semantic_cache_available = False
    state.callbacks = None
    state.external_provider_registry = None

    req = MagicMock()
    req.headers = {"content-type": "application/json"}
    req.query_params = {}
    req.method = "POST"
    req.url = "http://router/v1/chat/completions"
    req.app.state = state

    raw = json.dumps(body_dict).encode()

    async def body():
        return raw

    req.body = body
    return req


async def _run_routing_test(
    aliases,
    request_body,
    expect_model,
    expect_reasoning=None,
    expect_enable_thinking=None,
):
    """Route a request through route_general_request and verify the forwarded body."""
    router = RoundRobinRouter()
    setattr(router, "max_instance_failover_reroute_attempts", 0)
    req = _make_request(request_body, router)
    captured = {}

    async def fake_process(request, body, server_url, *a, **kw):
        captured["body"] = json.loads(body)
        yield MOCK_HEADERS, 200
        yield b'{"id":"x"}'

    with (
        patch(
            "vllm_router.services.request_service.request.get_service_discovery",
            return_value=_make_service_discovery(aliases),
        ),
        patch(
            "vllm_router.services.request_service.request.is_request_rewriter_initialized",
            return_value=False,
        ),
        patch(
            "vllm_router.services.request_service.request.process_request",
            side_effect=fake_process,
        ),
    ):
        from vllm_router.services.request_service.request import route_general_request

        resp = await route_general_request(req, "/v1/chat/completions", MagicMock())

    assert resp.status_code == 200
    assert captured["body"]["model"] == expect_model
    if expect_reasoning is not None:
        assert captured["body"]["reasoning_effort"] == expect_reasoning
    else:
        assert "reasoning_effort" not in captured["body"]
    if expect_enable_thinking is not None:
        assert (
            captured["body"]["chat_template_kwargs"]["enable_thinking"]
            == expect_enable_thinking
        )
    else:
        assert "chat_template_kwargs" not in captured["body"]


_MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_alias_injects_reasoning_effort():
    """When alias has reasoning_effort and request doesn't, it should be injected."""
    await _run_routing_test(
        aliases={
            "reasoning-model": AliasConfig(model="deepseek-r1", reasoning_effort="high")
        },
        request_body={
            "model": "reasoning-model",
            "stream": False,
            "messages": _MESSAGES,
        },
        expect_model="deepseek-r1",
        expect_reasoning="high",
    )


@pytest.mark.asyncio
async def test_client_reasoning_effort_not_overwritten():
    """When client already provides reasoning_effort, alias should NOT overwrite it."""
    await _run_routing_test(
        aliases={
            "reasoning-model": AliasConfig(model="deepseek-r1", reasoning_effort="high")
        },
        request_body={
            "model": "reasoning-model",
            "stream": False,
            "reasoning_effort": "low",
            "messages": _MESSAGES,
        },
        expect_model="deepseek-r1",
        expect_reasoning="low",
    )


@pytest.mark.asyncio
async def test_plain_alias_no_reasoning_effort():
    """A plain alias (no reasoning_effort) should not inject reasoning_effort."""
    await _run_routing_test(
        aliases={"short-name": AliasConfig(model="deepseek-r1")},
        request_body={"model": "short-name", "stream": False, "messages": _MESSAGES},
        expect_model="deepseek-r1",
    )


@pytest.mark.asyncio
async def test_legacy_plain_string_alias():
    """A plain-string alias value (from a custom ServiceDiscovery) must still work."""
    await _run_routing_test(
        aliases={"short-name": "deepseek-r1"},
        request_body={"model": "short-name", "stream": False, "messages": _MESSAGES},
        expect_model="deepseek-r1",
    )


@pytest.mark.asyncio
async def test_reasoning_effort_none_injects_enable_thinking_false():
    """When reasoning_effort is 'none', chat_template_kwargs.enable_thinking should be False."""
    await _run_routing_test(
        aliases={
            "no-thinking": AliasConfig(model="deepseek-r1", reasoning_effort="none")
        },
        request_body={
            "model": "no-thinking",
            "stream": False,
            "messages": _MESSAGES,
        },
        expect_model="deepseek-r1",
        expect_reasoning="none",
        expect_enable_thinking=False,
    )


@pytest.mark.asyncio
async def test_reasoning_effort_high_no_enable_thinking():
    """When reasoning_effort is not 'none', chat_template_kwargs should not be injected."""
    await _run_routing_test(
        aliases={
            "reasoning-model": AliasConfig(model="deepseek-r1", reasoning_effort="high")
        },
        request_body={
            "model": "reasoning-model",
            "stream": False,
            "messages": _MESSAGES,
        },
        expect_model="deepseek-r1",
        expect_reasoning="high",
    )
