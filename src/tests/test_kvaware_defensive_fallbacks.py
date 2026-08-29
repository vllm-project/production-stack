"""Defensive fallbacks in KvawareRouter.route_request.

Two crash paths observed/flagged in real deployments:
- no endpoints available -> unguarded ``endpoints[0]`` raised IndexError
  (LoadAwareRouter already answers 503; kvaware now mirrors it);
- the KV lookup matches an instance the ip mapping cannot place (several
  engines sharing one IP - QueryInstMsg keys instances by IP alone - or a
  stale registration) -> unhandled KeyError failed the whole request with
  a 500, even though session/QPS routing works fine without the cache hit.
"""

import pytest
from fastapi import HTTPException

from vllm_router.routers import routing_logic
from vllm_router.routers.routing_logic import HashRing, KvawareRouter


class _LookupMsg:
    def __init__(self, tokens, event_id):
        self.tokens = tokens
        self.event_id = event_id


class _QueryInstMsg:
    def __init__(self, ip, event_id):
        self.ip = ip
        self.event_id = event_id


@pytest.fixture(autouse=True)
def _lmcache_message_stubs(monkeypatch):
    # The lmcache import in routing_logic is guarded; the messages may be
    # absent in the test environment - stub the two types the router builds.
    monkeypatch.setattr(routing_logic, "LookupMsg", _LookupMsg, raising=False)
    monkeypatch.setattr(routing_logic, "QueryInstMsg", _QueryInstMsg, raising=False)


URL_A = "http://engine-a:8000"
URL_B = "http://engine-b:8000"


class Endpoint:
    def __init__(self, url):
        self.url = url
        self.model_names = ["m"]


class Tokenizer:
    @staticmethod
    def encode(prompt):
        return [1] * 8


class LookupRet:
    def __init__(self, layout_info):
        self.layout_info = layout_info


class QueryRet:
    # Real controllers answer QueryInstMsg with instance_id=None for IPs
    # they cannot attribute - exactly how the broken mapping arises.
    instance_id = None


def _bare_router():
    router = KvawareRouter.__new__(KvawareRouter)
    router.tokenizer = Tokenizer()
    router.threshold = 2000
    router.instance_id_to_ip = {}
    router.session_key = None
    router.hash_ring = HashRing()
    return router


@pytest.mark.asyncio
async def test_no_endpoints_answers_503_not_indexerror():
    router = _bare_router()
    with pytest.raises(HTTPException) as exc:
        await router.route_request([], {}, {}, None, {"prompt": "hello"})
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_unmapped_instance_falls_back_instead_of_500():
    router = _bare_router()

    async def query_manager(msg):
        if isinstance(msg, _LookupMsg):
            return LookupRet({"ghost-instance": ("LocalCPUBackend", 8)})
        return QueryRet()

    router.query_manager = query_manager
    url = await router.route_request(
        [Endpoint(URL_A), Endpoint(URL_B)], {}, {}, None, {"prompt": "hello"}
    )
    # QPS fallback with no stats picks the first endpoint - the request is
    # served, just without the cache-hit placement.
    assert url == URL_A
