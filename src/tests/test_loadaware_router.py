"""Unit tests for the `loadaware` routing logic.

`loadaware` places a request by `cache_hit_benefit - beta * relative_load`
over *every* endpoint, instead of `kvaware`'s "first instance reported to
hold the prefix". Both terms are dimensionless - a fraction of this prompt,
and a fraction of this fleet's mean load - so `beta` carries no unit from
the deployment. The scale-invariance and fleet-size tests below pin that
property directly, because it is what lets the policy ship a default
instead of a per-cluster calibration.

The tests build routers with `__new__` and set only the attributes the
methods under test read, so no LMCache controller (and no network) is
needed.
"""

from typing import Any, Dict

import pytest

import vllm_router.routers.routing_logic as routing_logic
from vllm_router.routers.routing_logic import (
    DEFAULT_LOADAWARE_BETA,
    LoadAwareRouter,
    RoutingLogic,
    _loadaware_beta,
)


@pytest.fixture(autouse=True)
def lookup_msg_stub(monkeypatch):
    """`LookupMsg`/`QueryInstMsg` come from the optional lmcache dependency;
    stub them when absent so the routing tests run without the lmcache
    extra."""

    class _Msg:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    for name in ("LookupMsg", "QueryInstMsg"):
        if not hasattr(routing_logic, name):
            monkeypatch.setattr(routing_logic, name, _Msg, raising=False)


URL_A = "http://10.0.0.1:8000"
URL_B = "http://10.0.0.2:8000"
URL_C = "http://10.0.0.3:8000"
URL_D = "http://10.0.0.4:8000"
INST_A = "instance-a"
INST_B = "instance-b"
RESTARTED_A = "instance-a2"
LOCAL = "LocalCPUBackend"
PROMPT_TOKENS = 2048


class EndpointInfo:
    def __init__(self, url: str, model_name: str = "test-model"):
        self.url = url
        self.model_names = [model_name]


class RequestStats:
    def __init__(
        self,
        qps: float = 0.0,
        in_prefill_requests: int = 0,
        in_decoding_requests: int = 0,
    ):
        self.qps = qps
        self.in_prefill_requests = in_prefill_requests
        self.in_decoding_requests = in_decoding_requests


class LookupRet:
    def __init__(self, layout_info: Dict[str, Any]):
        self.layout_info = layout_info


class InstRet:
    def __init__(self, instance_id: str):
        self.instance_id = instance_id


def endpoints(*urls):
    return [EndpointInfo(url=url) for url in urls]


def busy(in_prefill=0, in_decoding=0, qps=0.0):
    return RequestStats(
        qps=qps,
        in_prefill_requests=in_prefill,
        in_decoding_requests=in_decoding,
    )


def make_router(beta: float = DEFAULT_LOADAWARE_BETA, mapped: bool = True):
    """A LoadAwareRouter without the controller: only the attributes the
    selection-path methods read."""
    router = LoadAwareRouter.__new__(LoadAwareRouter)
    router.beta = beta
    router.instance_id_to_ip = {INST_A: URL_A, INST_B: URL_B} if mapped else {}
    return router


# --- the score ---------------------------------------------------------------


def test_all_cold_picks_the_idle_instance():
    """No cache anywhere: the score is pure load penalty."""
    router = make_router(beta=0.1)
    stats = {URL_A: busy(in_decoding=4), URL_B: busy(in_decoding=1)}
    assert router.select_url(endpoints(URL_A, URL_B), stats, {}, PROMPT_TOKENS) == URL_B


def test_equally_idle_picks_the_warmest_instance():
    """No load anywhere: the score is pure cache-hit benefit."""
    router = make_router(beta=0.1)
    layout = {INST_A: (LOCAL, 512), INST_B: (LOCAL, 2048)}
    assert (
        router.select_url(endpoints(URL_A, URL_B), {}, layout, PROMPT_TOKENS) == URL_B
    )


def test_warm_but_loaded_loses_to_cold_but_idle():
    """The point of the policy: a lopsided fleet outweighs a full hit.

    Loads are 12 and 0, so mean = 6 and the relative loads are +1.0 and -1.0:

        benefit(A) = 2048/2048 = 1.0, rel(A) = +1.0 -> 1.0 - 1.0*(+1.0) =  0.0
        benefit(B) = 0,               rel(B) = -1.0 -> 0.0 - 1.0*(-1.0) = +1.0
    """
    router = make_router(beta=1.0)
    layout = {INST_A: (LOCAL, PROMPT_TOKENS)}
    stats = {URL_A: busy(in_prefill=4, in_decoding=8), URL_B: busy()}
    assert (
        router.select_url(endpoints(URL_A, URL_B), stats, layout, PROMPT_TOKENS)
        == URL_B
    )


def test_warm_but_loaded_wins_when_beta_is_small():
    """Same fixture, smaller beta: the crossover moves. This is the sweep axis."""
    router = make_router(beta=0.01)
    layout = {INST_A: (LOCAL, PROMPT_TOKENS)}
    stats = {URL_A: busy(in_prefill=4, in_decoding=8), URL_B: busy()}
    assert (
        router.select_url(endpoints(URL_A, URL_B), stats, layout, PROMPT_TOKENS)
        == URL_A
    )


def test_beta_zero_is_cache_only_placement():
    """beta = 0 degenerates to "most cached wins", however loaded it is."""
    router = make_router(beta=0.0)
    layout = {INST_A: (LOCAL, PROMPT_TOKENS)}
    stats = {URL_A: busy(in_decoding=100), URL_B: busy()}
    assert (
        router.select_url(endpoints(URL_A, URL_B), stats, layout, PROMPT_TOKENS)
        == URL_A
    )


def test_the_same_beta_is_the_same_policy_at_ten_times_the_load():
    """Scale invariance - the property that lets `beta` ship a default.

    Absolute counts do not have this: a beta tuned where the fleet ran
    4-and-1 would, on a fleet running 400-and-100, charge a penalty far past
    the benefit cap of 1.0, and placement would silently collapse to
    least-loaded. Relative load reads both fleets identically.
    """
    router = make_router(beta=0.5)
    layout = {INST_A: (LOCAL, PROMPT_TOKENS)}
    small = {URL_A: busy(in_decoding=4), URL_B: busy(in_decoding=1)}
    large = {URL_A: busy(in_decoding=400), URL_B: busy(in_decoding=100)}
    assert router.relative_loads(small, endpoints(URL_A, URL_B)) == pytest.approx(
        router.relative_loads(large, endpoints(URL_A, URL_B))
    )
    assert router.select_url(
        endpoints(URL_A, URL_B), small, layout, PROMPT_TOKENS
    ) == router.select_url(endpoints(URL_A, URL_B), large, layout, PROMPT_TOKENS)


def test_relative_load_is_measured_against_the_whole_fleet_not_a_pair():
    """Four engines, loads 12/0/0/0: mean is 3, so the hot engine reads +3.0
    and each idle one reads -1.0."""
    router = make_router()
    stats = {
        URL_A: busy(in_decoding=12),
        URL_B: busy(),
        URL_C: busy(),
        URL_D: busy(),
    }
    relative = router.relative_loads(stats, endpoints(URL_A, URL_B, URL_C, URL_D))
    assert relative[URL_A] == pytest.approx(3.0)
    assert relative[URL_B] == pytest.approx(-1.0)


def test_a_near_idle_fleet_reports_no_imbalance_to_act_on():
    """The denominator clamp: at mean load 0.5, one in-flight request must not
    read as a 100%-overloaded engine. Without `max(1, mean)` it would read
    +1.0; with it, +0.5."""
    router = make_router()
    stats = {URL_A: busy(in_decoding=1), URL_B: busy()}
    relative = router.relative_loads(stats, endpoints(URL_A, URL_B))
    assert relative[URL_A] == pytest.approx(0.5)
    assert relative[URL_B] == pytest.approx(-0.5)


def test_benefit_is_normalized_so_the_weights_are_prompt_length_invariant():
    """Half a prompt cached is the same benefit for a short and a long prompt."""
    router = make_router()
    assert router.score_endpoint(256, 512, 0.0) == pytest.approx(
        router.score_endpoint(2048, 4096, 0.0)
    )


def test_benefit_is_capped_at_one_full_prompt():
    """`matched_tokens` can exceed the prompt when the match is rounded up to a
    chunk boundary; it must not outrank a genuine full hit."""
    router = make_router()
    assert router.score_endpoint(2304, 2048, 0.0) == pytest.approx(1.0)


def test_ties_are_broken_by_url_for_reproducibility():
    router = make_router()
    layout = {INST_A: (LOCAL, 1024), INST_B: (LOCAL, 1024)}
    assert (
        router.select_url(endpoints(URL_B, URL_A), {}, layout, PROMPT_TOKENS) == URL_A
    )


def test_no_endpoints_returns_none_for_the_caller_to_fall_back():
    router = make_router()
    assert router.select_url([], {}, {}, PROMPT_TOKENS) is None


def test_missing_request_stats_counts_as_no_load():
    """A URL absent from request_stats has served nothing - load 0, the same
    reading `_qps_routing` gives an unseen endpoint."""
    assert LoadAwareRouter.load_penalty({}, URL_A) == 0
    assert LoadAwareRouter.load_penalty(None, URL_A) == 0


def test_load_penalty_counts_prefill_and_decode():
    stats = {URL_A: busy(in_prefill=3, in_decoding=4)}
    assert LoadAwareRouter.load_penalty(stats, URL_A) == 7


# --- the instance_id -> URL bridge -------------------------------------------


def test_holder_missing_from_the_instance_map_scores_no_benefit():
    """A holder the bridge cannot name earns no credit; the idle mapped
    endpoint wins on load."""
    router = make_router(mapped=False)
    router.instance_id_to_ip = {INST_B: URL_B}
    layout = {INST_A: (LOCAL, PROMPT_TOKENS)}
    stats = {URL_A: busy(in_decoding=2), URL_B: busy()}
    assert (
        router.select_url(endpoints(URL_A, URL_B), stats, layout, PROMPT_TOKENS)
        == URL_B
    )


def test_the_live_instance_id_wins_when_two_ids_share_a_url():
    """A restarted engine registers under a fresh id; the dead id lingers.
    Insertion order resolves it: the last id written for a URL is the live
    one, and only it is credited."""
    router = make_router(mapped=False)
    router.instance_id_to_ip = {INST_A: URL_A, INST_B: URL_B, RESTARTED_A: URL_A}
    layout = {RESTARTED_A: (LOCAL, 512)}
    assert router.matched_tokens_by_url(layout) == {URL_A: 512}


def test_a_dead_instance_id_earns_no_phantom_credit():
    """The dead id still appears as a holder in `layout_info`, but the
    restarted engine came back empty: its match must not be credited."""
    router = make_router(mapped=False)
    router.instance_id_to_ip = {INST_A: URL_A, INST_B: URL_B, RESTARTED_A: URL_A}
    layout = {INST_A: (LOCAL, PROMPT_TOKENS)}
    assert router.matched_tokens_by_url(layout) == {}


def test_an_unmapped_endpoint_makes_the_bridge_stale():
    router = make_router(mapped=False)
    router.instance_id_to_ip = {INST_A: URL_A}
    assert router.instance_map_is_stale(endpoints(URL_A, URL_B), {})


def test_an_unknown_holder_makes_the_bridge_stale():
    """What an engine restart looks like: `layout_info` names an id the
    bridge has never seen."""
    router = make_router()
    assert router.instance_map_is_stale(
        endpoints(URL_A, URL_B), {RESTARTED_A: (LOCAL, 512)}
    )


def test_a_fully_mapped_bridge_with_known_holders_is_not_stale():
    router = make_router()
    assert not router.instance_map_is_stale(
        endpoints(URL_A, URL_B), {INST_A: (LOCAL, 512)}
    )


# --- routing entry point ------------------------------------------------------


@pytest.mark.asyncio
async def test_route_request_scores_and_routes_to_the_argmax():
    """End to end through `route_request` with the controller faked: the warm
    endpoint is saturated, so the idle one wins."""
    router = make_router(beta=1.0)

    class Tokenizer:
        def encode(self, _prompt):
            return list(range(PROMPT_TOKENS))

    router.tokenizers = {"test-model": Tokenizer()}

    async def query_manager(msg):
        if hasattr(msg, "tokens"):
            return LookupRet({INST_A: (LOCAL, PROMPT_TOKENS)})
        return InstRet(INST_A)

    router.query_manager = query_manager
    stats = {URL_A: busy(in_prefill=4, in_decoding=8), URL_B: busy()}
    url = await router.route_request(
        endpoints(URL_A, URL_B), {}, stats, None, {"prompt": "x"}
    )
    assert url == URL_B
    assert (url.algorithm, url.decision, url.reason) == (
        "loadaware",
        "primary",
        "load_aware",
    )


@pytest.mark.asyncio
async def test_no_cached_prefix_anywhere_falls_back_to_qps():
    """An empty `layout_info` means there is no benefit term to weigh: the
    request takes the upstream session/QPS fallback, not a crash."""
    from uhashring import HashRing

    router = make_router()

    class Tokenizer:
        def encode(self, _prompt):
            return list(range(PROMPT_TOKENS))

    router.tokenizers = {"test-model": Tokenizer()}

    async def query_manager(_msg):
        return LookupRet({})

    router.query_manager = query_manager
    router.session_key = "x-user-id"
    router.hash_ring = HashRing()

    class Request:
        headers: Dict[str, str] = {}

    stats = {URL_A: busy(qps=5.0), URL_B: busy(qps=1.0)}
    url = await router.route_request(
        endpoints(URL_A, URL_B), {}, stats, Request(), {"prompt": "x"}
    )
    assert url == URL_B
    assert (url.algorithm, url.decision, url.reason) == (
        "loadaware",
        "fallback",
        "no_cache_match",
    )


@pytest.mark.asyncio
async def test_same_url_restart_does_not_credit_the_old_instance_id():
    """A restart can retain its URL while changing LMCache identity. Even when
    the old holder is already known, routing must validate the endpoint's live
    identity before awarding cache credit."""
    from uhashring import HashRing

    router = make_router()

    class Tokenizer:
        def encode(self, _prompt):
            return list(range(PROMPT_TOKENS))

    router.tokenizers = {"test-model": Tokenizer()}
    queried_ips = []

    async def query_manager(msg):
        if hasattr(msg, "tokens"):
            return LookupRet({INST_A: (LOCAL, PROMPT_TOKENS)})
        queried_ips.append(msg.ip)
        return InstRet(RESTARTED_A)

    router.query_manager = query_manager
    router.session_key = "x-user-id"
    router.hash_ring = HashRing()

    class Request:
        headers: Dict[str, str] = {}

    stats = {URL_A: busy(qps=5.0), URL_B: busy(qps=1.0)}
    url = await router.route_request(
        endpoints(URL_A, URL_B), {}, stats, Request(), {"prompt": "x"}
    )

    assert queried_ips == ["10.0.0.1"]
    assert url == URL_B
    assert (url.algorithm, url.decision, url.reason) == (
        "loadaware",
        "fallback",
        "no_live_holder",
    )


@pytest.mark.asyncio
async def test_only_unavailable_cache_holders_fall_back_to_qps():
    from uhashring import HashRing

    router = make_router(mapped=False)
    router.instance_id_to_ip = {
        INST_A: URL_A,
        RESTARTED_A: URL_A,
        INST_B: URL_B,
    }

    class Tokenizer:
        def encode(self, _prompt):
            return list(range(PROMPT_TOKENS))

    router.tokenizers = {"test-model": Tokenizer()}

    async def query_manager(msg):
        if hasattr(msg, "tokens"):
            return LookupRet({INST_A: (LOCAL, PROMPT_TOKENS)})
        return InstRet(RESTARTED_A)

    router.query_manager = query_manager
    router.session_key = "x-user-id"
    router.hash_ring = HashRing()

    class Request:
        headers: Dict[str, str] = {}

    stats = {URL_A: busy(qps=5.0), URL_B: busy(qps=1.0)}
    url = await router.route_request(
        endpoints(URL_A, URL_B), {}, stats, Request(), {"prompt": "x"}
    )

    assert url == URL_B
    assert (url.algorithm, url.decision, url.reason) == (
        "loadaware",
        "fallback",
        "no_live_holder",
    )


@pytest.mark.asyncio
async def test_only_stale_holder_url_outside_current_endpoints_falls_back_to_qps():
    from uhashring import HashRing

    router = make_router()
    router.instance_id_to_ip["instance-c"] = URL_C

    class Tokenizer:
        def encode(self, _prompt):
            return list(range(PROMPT_TOKENS))

    router.tokenizers = {"test-model": Tokenizer()}

    async def query_manager(_msg):
        return LookupRet({"instance-c": (LOCAL, PROMPT_TOKENS)})

    router.query_manager = query_manager
    router.session_key = "x-user-id"
    router.hash_ring = HashRing()

    class Request:
        headers: Dict[str, str] = {}

    stats = {URL_A: busy(qps=5.0), URL_B: busy(qps=1.0)}
    url = await router.route_request(
        endpoints(URL_A, URL_B), {}, stats, Request(), {"prompt": "x"}
    )

    assert url == URL_B
    assert (url.algorithm, url.decision, url.reason) == (
        "loadaware",
        "fallback",
        "no_live_holder",
    )


@pytest.mark.asyncio
async def test_tokenize_prompt_uses_tokenizer_for_each_model(monkeypatch):
    loaded_models = []

    class ModelTokenizer:
        def __init__(self, token_id):
            self.token_id = token_id

        def encode(self, _prompt):
            return [self.token_id]

    tokenizers = {
        "model-a": ModelTokenizer(1),
        "model-b": ModelTokenizer(2),
    }

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(model_name):
            loaded_models.append(model_name)
            return tokenizers[model_name]

    monkeypatch.setattr(
        routing_logic, "AutoTokenizer", FakeAutoTokenizer, raising=False
    )
    router = make_router()
    router.tokenizers = {}

    token_ids = []
    for model_name in ("model-a", "model-b", "model-a"):
        token_ids.append(
            await router.tokenize_prompt(
                [EndpointInfo(URL_A, model_name)], {"prompt": "test"}
            )
        )

    assert loaded_models == ["model-a", "model-b"]
    assert token_ids == [[1], [2], [1]]


@pytest.mark.asyncio
async def test_no_endpoints_is_a_503_not_a_crash():
    from fastapi import HTTPException

    router = make_router()
    with pytest.raises(HTTPException) as exc_info:
        await router.route_request([], {}, {}, None, {"prompt": "x"})
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_instance_map_refresh_queries_endpoints_concurrently():
    """The refresh must gather its controller round-trips, not serialize
    them: with two endpoints, both queries must be in flight together."""
    import asyncio

    router = make_router(mapped=False)
    in_flight = 0
    max_in_flight = 0

    async def query_manager(msg):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return InstRet("instance-" + msg.ip)

    router.query_manager = query_manager
    await router.refresh_instance_map(endpoints(URL_A, URL_B), {})
    assert max_in_flight == 2
    assert router.instance_id_to_ip == {
        "instance-10.0.0.1": URL_A,
        "instance-10.0.0.2": URL_B,
    }


# --- bursts --------------------------------------------------------------------


INST_C = "instance-c"
BURST = 128
BURST_PROMPT_TOKENS = 32000
SHARED_PREFIX_TOKENS = 512


@pytest.fixture
def stats_monitor():
    from vllm_router.stats.request_stats import RequestStatsMonitor, SingletonMeta

    SingletonMeta._instances.pop(RequestStatsMonitor, None)
    monitor = RequestStatsMonitor(sliding_window_size=60)
    yield monitor
    SingletonMeta._instances.pop(RequestStatsMonitor, None)


async def route_burst(router, monitor, layout_info=None):
    """Route BURST concurrent requests the way `route_general_request` and
    `process_request` do: snapshot `request_stats`, await `route_request`,
    then `on_new_request` on the chosen endpoint (no await in between)."""
    import asyncio
    import random
    import time
    from collections import Counter
    from types import SimpleNamespace

    rng = random.Random(0)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(request_stats_monitor=monitor)),
        headers={},
    )

    class Tokenizer:
        def encode(self, _prompt):
            return list(range(BURST_PROMPT_TOKENS))

    router.tokenizers = {"test-model": Tokenizer()}

    instance_by_ip = {
        url.split("//", 1)[1].split(":", 1)[0]: instance_id
        for instance_id, url in router.instance_id_to_ip.items()
    }

    async def query_manager(msg):
        if not hasattr(msg, "tokens"):
            # Live identity check of a cache holder: unchanged instance.
            return InstRet(instance_by_ip[msg.ip])
        # Controller round-trip: the await during which the rest of the
        # burst is routed.
        await asyncio.sleep(rng.uniform(0.001, 0.02))
        if layout_info is not None:
            return LookupRet(layout_info)
        # Only a short shared prefix (e.g. a common system prompt) is cached,
        # on one endpoint.
        return LookupRet({INST_A: (LOCAL, SHARED_PREFIX_TOKENS)})

    router.query_manager = query_manager
    fleet = endpoints(URL_A, URL_B, URL_C)

    async def one(i):
        snapshot = monitor.get_request_stats(time.time())
        url = await router.route_request(fleet, {}, snapshot, request, {"prompt": "x"})
        monitor.on_new_request(url, f"req-{i}", time.time())
        return url

    return Counter(await asyncio.gather(*(one(i) for i in range(BURST))))


def burst_router():
    router = make_router(beta=DEFAULT_LOADAWARE_BETA)
    router.instance_id_to_ip = {INST_A: URL_A, INST_B: URL_B, INST_C: URL_C}
    return router


@pytest.mark.asyncio
async def test_a_stale_snapshot_herds_a_burst_onto_one_endpoint(
    stats_monitor, monkeypatch
):
    """The failure mode: scored against the pre-burst snapshot, every request
    sees equal load, so the small prefix match on A wins every time."""
    monkeypatch.setattr(
        LoadAwareRouter,
        "live_request_stats",
        staticmethod(lambda _request, request_stats: request_stats),
    )
    placement = await route_burst(burst_router(), stats_monitor)
    assert placement == {URL_A: BURST}


@pytest.mark.asyncio
async def test_a_burst_is_spread_by_live_load(stats_monitor):
    """With the live load read after the awaits, each decision sees the
    requests placed before it, and the burst spreads over the fleet."""
    placement = await route_burst(burst_router(), stats_monitor)
    assert sum(placement.values()) == BURST
    assert set(placement) == {URL_A, URL_B, URL_C}
    assert max(placement.values()) <= BURST // 2


@pytest.mark.asyncio
async def test_a_cold_burst_is_spread_by_live_load(stats_monitor):
    """Nothing cached anywhere: the fallback must also see live load."""
    from uhashring import HashRing

    router = burst_router()
    router.session_key = "x-user-id"
    router.hash_ring = HashRing()
    placement = await route_burst(router, stats_monitor, layout_info={})
    assert sum(placement.values()) == BURST
    assert max(placement.values()) <= BURST // 2


def test_live_request_stats_reads_the_monitor_now(stats_monitor):
    import time
    from types import SimpleNamespace

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(request_stats_monitor=stats_monitor))
    )
    stale = stats_monitor.get_request_stats(time.time())
    stats_monitor.on_new_request(URL_A, "req-1", time.time())

    live = LoadAwareRouter.live_request_stats(request, stale)
    assert live[URL_A].in_prefill_requests == 1
    assert URL_A not in stale


def test_live_request_stats_keeps_the_snapshot_without_a_monitor():
    snapshot = {URL_A: busy(in_decoding=3)}
    assert LoadAwareRouter.live_request_stats(None, snapshot) is snapshot


# --- chat completions lookup ---------------------------------------------------


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


@pytest.fixture
def tokenize_calls(monkeypatch):
    """Capture `/tokenize` POSTs and answer with fixed token ids."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return FakeResponse({"tokens": [1, 2, 3], "count": 3})

    monkeypatch.setattr(routing_logic.requests, "post", fake_post)
    return calls


class QpsFallbackRequest:
    headers: Dict[str, str] = {}


def make_fallback_router(beta: float = DEFAULT_LOADAWARE_BETA):
    """A router that can also take the session/QPS fallback route."""
    from uhashring import HashRing

    router = make_router(beta=beta)
    router.session_key = "x-user-id"
    router.hash_ring = HashRing()
    return router


@pytest.mark.asyncio
async def test_chat_request_is_tokenized_with_the_engine_chat_template(
    tokenize_calls,
):
    """`messages` go to the engine's `/tokenize` (chat template applied), not
    through `prompt`, which a chat request does not have."""
    router = make_router()
    request_json = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "tools": [{"type": "function", "function": {"name": "f"}}],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    tokens = await router.tokenize_prompt(endpoints(URL_A), request_json)

    assert tokens == [1, 2, 3]
    assert len(tokenize_calls) == 1
    call = tokenize_calls[0]
    assert call["url"] == URL_A + "/tokenize"
    assert call["json"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hello"}],
        "add_generation_prompt": True,
        "tools": [{"type": "function", "function": {"name": "f"}}],
        "chat_template_kwargs": {"enable_thinking": False},
    }


@pytest.mark.asyncio
async def test_text_only_list_content_is_flattened_before_tokenize(tokenize_calls):
    """vLLM's `/tokenize` rejects list content on a text-only model; text parts
    are joined with a newline, as vLLM's chat_utils renders them."""
    router = make_router()
    request_json = {
        "messages": [
            {"role": "system", "content": "sys"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part one"},
                    {"type": "text", "text": "part two"},
                ],
            },
        ],
        "add_generation_prompt": False,
    }
    await router.tokenize_prompt(endpoints(URL_A), request_json)

    sent = tokenize_calls[0]["json"]
    assert sent["messages"][1]["content"] == "part one\npart two"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["add_generation_prompt"] is False
    # The client's request body is not mutated.
    assert isinstance(request_json["messages"][1]["content"], list)


@pytest.mark.asyncio
async def test_list_content_with_non_text_parts_is_left_unchanged(tokenize_calls):
    router = make_router()
    content = [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
    ]
    await router.tokenize_prompt(
        endpoints(URL_A), {"messages": [{"role": "user", "content": content}]}
    )
    assert tokenize_calls[0]["json"]["messages"][0]["content"] == content


@pytest.mark.asyncio
async def test_completions_prompt_still_uses_the_local_tokenizer(tokenize_calls):
    router = make_router()

    class Tokenizer:
        def encode(self, prompt):
            return [len(prompt)]

    router.tokenizers = {"test-model": Tokenizer()}
    tokens = await router.tokenize_prompt(endpoints(URL_A), {"prompt": "abcd"})

    assert tokens == [4]
    assert tokenize_calls == []


@pytest.mark.asyncio
async def test_tokenize_error_body_raises_a_clear_error(monkeypatch):
    """An engine error body has no `tokens`; say so instead of a bare
    `KeyError: 'tokens'`."""

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse({"error": {"message": "boom"}}, status_code=400)

    monkeypatch.setattr(routing_logic.requests, "post", fake_post)
    router = make_router()
    with pytest.raises(RuntimeError, match="returned 400"):
        await router.tokenize_prompt(
            endpoints(URL_A), {"messages": [{"role": "user", "content": "x"}]}
        )


@pytest.mark.asyncio
async def test_tokenize_non_json_response_raises_a_clear_error(monkeypatch):
    """A non-JSON reply (e.g. an HTML error page from a proxy) is reported
    with its status code and body, not as a bare JSON decode error."""

    class HtmlResponse:
        status_code = 502
        text = "<html>Bad Gateway</html>"

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(
        routing_logic.requests,
        "post",
        lambda url, headers=None, json=None, timeout=None: HtmlResponse(),
    )
    router = make_router()
    with pytest.raises(RuntimeError, match="returned 502 \\(non-JSON\\): <html>Bad"):
        await router.tokenize_prompt(
            endpoints(URL_A), {"messages": [{"role": "user", "content": "x"}]}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("messages", [None, "not a list"])
async def test_malformed_messages_are_passed_through_to_tokenize(
    tokenize_calls, messages
):
    """A `messages` that is not a list must not crash the flattening; it is
    sent as-is for the engine's `/tokenize` to validate."""
    router = make_router()
    await router.tokenize_prompt(endpoints(URL_A), {"messages": messages})
    assert tokenize_calls[0]["json"]["messages"] == messages


@pytest.mark.asyncio
async def test_route_request_falls_back_when_tokenize_fails(monkeypatch):
    """A failing `/tokenize` (e.g. an engine restarting) must not turn into an
    HTTP 500: the request takes the session/QPS fallback route."""

    def fake_post(url, headers=None, json=None, timeout=None):
        raise ConnectionError("engine restarting")

    monkeypatch.setattr(routing_logic.requests, "post", fake_post)
    router = make_fallback_router()

    async def query_manager(_msg):
        raise AssertionError("lookup must not run without token ids")

    router.query_manager = query_manager
    stats = {URL_A: busy(qps=5.0), URL_B: busy(qps=1.0)}
    url = await router.route_request(
        endpoints(URL_A, URL_B),
        {},
        stats,
        QpsFallbackRequest(),
        {"messages": [{"role": "user", "content": "x"}]},
    )
    assert url == URL_B


@pytest.mark.asyncio
async def test_route_request_falls_back_when_the_lookup_fails(tokenize_calls):
    router = make_fallback_router()

    async def query_manager(_msg):
        raise TimeoutError("controller unavailable")

    router.query_manager = query_manager
    stats = {URL_A: busy(qps=1.0), URL_B: busy(qps=5.0)}
    url = await router.route_request(
        endpoints(URL_A, URL_B),
        {},
        stats,
        QpsFallbackRequest(),
        {"messages": [{"role": "user", "content": "x"}]},
    )
    assert url == URL_A
    assert (url.algorithm, url.decision, url.reason) == (
        "loadaware",
        "fallback",
        "backend_error",
    )


@pytest.mark.asyncio
async def test_chat_request_routes_to_the_replica_holding_its_prefix(
    tokenize_calls,
):
    """End to end: a chat request is looked up by its chat-template tokens
    and lands on the replica reported to hold them."""
    router = make_router(beta=0.5)
    looked_up = []

    async def query_manager(msg):
        if not hasattr(msg, "tokens"):
            return InstRet(INST_B)
        looked_up.append(msg.tokens)
        return LookupRet({INST_B: (LOCAL, 3)})

    router.query_manager = query_manager
    url = await router.route_request(
        endpoints(URL_A, URL_B),
        {},
        {},
        None,
        {"messages": [{"role": "user", "content": "x"}]},
    )
    assert tokenize_calls[0]["json"]["messages"] == [{"role": "user", "content": "x"}]
    assert "prompt" not in tokenize_calls[0]["json"]
    assert looked_up == [[1, 2, 3]]
    assert url == URL_B


# --- configuration ------------------------------------------------------------


def test_loadaware_is_a_routing_logic_value():
    assert RoutingLogic("loadaware") is RoutingLogic.LOADAWARE


def test_the_default_beta_is_the_documented_one():
    assert DEFAULT_LOADAWARE_BETA == 1.0
    assert _loadaware_beta(None) == 1.0


def test_beta_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("LOADAWARE_BETA", "0.25")
    assert _loadaware_beta(None) == 0.25


def test_explicit_beta_beats_the_environment(monkeypatch):
    monkeypatch.setenv("LOADAWARE_BETA", "0.25")
    assert _loadaware_beta(2.0) == 2.0


def test_zero_from_the_environment_is_honoured_not_treated_as_unset(monkeypatch):
    monkeypatch.setenv("LOADAWARE_BETA", "0")
    assert _loadaware_beta(None) == 0.0


def test_garbage_in_the_environment_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("LOADAWARE_BETA", "fast")
    assert _loadaware_beta(None) == DEFAULT_LOADAWARE_BETA
