"""Unit tests for the KV-cache-aware routing logic."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import vllm_router.routers.routing_logic as routing_logic
from vllm_router.dynamic_config import DynamicConfigWatcher, DynamicRouterConfig
from vllm_router.routers.routing_logic import KvawareRouter


@pytest.fixture(autouse=True)
def lmcache_message_stubs(monkeypatch):
    """Stub optional LMCache messages when the extra is not installed."""

    class _Msg:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    for name in ("LookupMsg", "QueryInstMsg"):
        if not hasattr(routing_logic, name):
            monkeypatch.setattr(routing_logic, name, _Msg, raising=False)


class EndpointInfo:
    def __init__(self, url, model_name="test-model"):
        self.url = url
        self.model_names = [model_name]


class Tokenizer:
    def encode(self, prompt):
        return list(range(1000))


@pytest.mark.parametrize(
    "threshold",
    [
        pytest.param(900, id="both-matches-pass-threshold"),
        pytest.param(0, id="only-longest-match-passes-threshold"),
    ],
)
@pytest.mark.asyncio
async def test_kvaware_routes_to_longest_reported_prefix(threshold):
    url_a = "http://10.0.0.1:8000"
    url_b = "http://10.0.0.2:8000"
    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizers = {"test-model": Tokenizer()}
    router.threshold = threshold
    router.session_key = "x-session-id"
    router.hash_ring = routing_logic.HashRing()
    router.instance_id_to_ip = {
        "instance-a": url_a,
        "instance-b": url_b,
    }

    async def query_manager(_msg):
        return SimpleNamespace(
            layout_info={
                "instance-a": ("LocalCPUBackend", 100),
                "instance-b": ("LocalCPUBackend", 1000),
            }
        )

    router.query_manager = query_manager
    endpoints = [EndpointInfo(url_a), EndpointInfo(url_b)]
    request_stats = {
        url_a: SimpleNamespace(qps=0),
        url_b: SimpleNamespace(qps=1),
    }

    selected = await router.route_request(
        endpoints,
        {},
        request_stats,
        SimpleNamespace(headers={}),
        {"prompt": "test"},
    )

    assert selected == url_b


@pytest.mark.asyncio
async def test_kvaware_uses_tokenizer_for_each_model(monkeypatch):
    loaded_models = []
    lookup_tokens = []

    class ModelTokenizer:
        def __init__(self, token_id):
            self.token_id = token_id

        def encode(self, _prompt):
            return [self.token_id]

    tokenizers = {
        "model-a": ModelTokenizer(1),
        "model-b": ModelTokenizer(2),
    }

    def load_tokenizer(model_name):
        loaded_models.append(model_name)
        return tokenizers[model_name]

    monkeypatch.setattr(
        routing_logic,
        "AutoTokenizer",
        SimpleNamespace(from_pretrained=load_tokenizer),
        raising=False,
    )

    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizers = {}
    router.threshold = 0
    router.session_key = "x-session-id"
    router.hash_ring = routing_logic.HashRing()
    router.instance_id_to_ip = {}

    async def query_manager(msg):
        lookup_tokens.append(msg.tokens)
        return SimpleNamespace(layout_info={})

    router.query_manager = query_manager

    for model_name, url in (
        ("model-a", "http://10.0.0.1:8000"),
        ("model-b", "http://10.0.0.2:8000"),
    ):
        await router.route_request(
            [EndpointInfo(url, model_name)],
            {},
            {},
            SimpleNamespace(headers={}),
            {"prompt": "test"},
        )

    assert loaded_models == ["model-a", "model-b"]
    assert lookup_tokens == [[1], [2]]


@pytest.mark.parametrize(
    "instance_map",
    [
        pytest.param(
            {
                "dead-instance": "http://10.0.0.9:8000",
                "instance-a": "http://10.0.0.1:8000",
                "instance-b": "http://10.0.0.2:8000",
            },
            id="dead-pod-url",
        ),
        pytest.param(
            {
                "dead-instance": "http://10.0.0.1:8000",
                "instance-b": "http://10.0.0.2:8000",
                "instance-a": "http://10.0.0.1:8000",
            },
            id="restarted-instance-same-url",
        ),
    ],
)
@pytest.mark.asyncio
async def test_kvaware_ignores_cached_dead_holder(instance_map):
    url_a = "http://10.0.0.1:8000"
    url_b = "http://10.0.0.2:8000"
    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizers = {"test-model": Tokenizer()}
    router.threshold = 1000
    router.session_key = "x-session-id"
    router.hash_ring = routing_logic.HashRing()
    router.instance_id_to_ip = instance_map

    async def query_manager(_msg):
        return SimpleNamespace(
            layout_info={
                "dead-instance": ("LocalCPUBackend", 1000),
                "instance-b": ("LocalCPUBackend", 800),
            }
        )

    router.query_manager = query_manager
    selected = await router.route_request(
        [EndpointInfo(url_a), EndpointInfo(url_b)],
        {},
        {},
        SimpleNamespace(headers={}),
        {"prompt": "test"},
    )

    assert selected == url_b


@pytest.mark.asyncio
async def test_kvaware_refreshes_unknown_dead_holder_and_uses_live_match():
    url_a = "http://10.0.0.1:8000"
    url_b = "http://10.0.0.2:8000"
    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizers = {"test-model": Tokenizer()}
    router.threshold = 1000
    router.session_key = "x-session-id"
    router.hash_ring = routing_logic.HashRing()
    router.instance_id_to_ip = {"instance-b": url_b}

    async def query_manager(msg):
        if hasattr(msg, "tokens"):
            return SimpleNamespace(
                layout_info={
                    "dead-instance": ("LocalCPUBackend", 1000),
                    "instance-b": ("LocalCPUBackend", 800),
                }
            )
        instance_id = "instance-a" if msg.ip == "10.0.0.1" else "instance-b"
        return SimpleNamespace(instance_id=instance_id)

    router.query_manager = query_manager
    selected = await router.route_request(
        [EndpointInfo(url_a), EndpointInfo(url_b)],
        {},
        {},
        SimpleNamespace(headers={}),
        {"prompt": "test"},
    )

    assert selected == url_b


def test_dynamic_config_reload_keeps_kvaware_settings(monkeypatch):
    manager_args = {}

    class ControllerManager:
        def __init__(self, urls, **kwargs):
            manager_args.update(urls=urls, **kwargs)

    monkeypatch.setattr(
        routing_logic,
        "controller_manager",
        SimpleNamespace(LMCacheControllerManager=ControllerManager),
        raising=False,
    )
    monkeypatch.setattr(KvawareRouter, "start_kv_manager", lambda self: None)
    config = DynamicRouterConfig(
        service_discovery="static",
        routing_logic="kvaware",
        kv_aware_threshold=500,
        lmcache_controller_port=9100,
        lmcache_controller_reply_port=9101,
        lmcache_controller_heartbeat_port=9102,
        lmcache_health_check_interval=7,
        lmcache_worker_timeout=11,
    )
    watcher = SimpleNamespace(app=MagicMock())

    try:
        DynamicConfigWatcher.reconfigure_routing_logic(watcher, config)
        assert watcher.app.state.router.threshold == 500
    finally:
        routing_logic.cleanup_routing_logic()
    assert manager_args == {
        "urls": {
            "pull": "0.0.0.0:9100",
            "reply": "0.0.0.0:9101",
            "heartbeat": "0.0.0.0:9102",
        },
        "health_check_interval": 7,
        "lmcache_worker_timeout": 11,
    }
