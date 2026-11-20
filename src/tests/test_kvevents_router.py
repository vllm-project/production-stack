"""Tests for the vLLM KV event index and the ``kvevents`` routing logic."""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import msgpack
import pytest

from vllm_router.dynamic_config import DynamicConfigWatcher, DynamicRouterConfig
from vllm_router.routers.kv_event_index import (
    MEDIUM_CPU,
    MEDIUM_GPU,
    KvEventIndex,
    KvEventSubscriber,
    kv_events_endpoint,
    prompt_chain,
)
from vllm_router.routers.routing_logic import (
    KvEventAwareRouter,
    RoutingLogic,
    cleanup_routing_logic,
    initialize_routing_logic,
    reconfigure_routing_logic,
)

A = "http://10.0.0.1:8000"
B = "http://10.0.0.2:8000"


def stored(hashes, parent, tokens, block_size, medium="GPU", group=None, **kw):
    ev = {
        "type": "BlockStored",
        "block_hashes": hashes,
        "parent_block_hash": parent,
        "token_ids": tokens,
        "block_size": block_size,
        "lora_id": None,
        "medium": medium,
        "lora_name": None,
    }
    if group is not None:
        ev["group_idx"] = group
    ev.update(kw)
    return ev


def removed(hashes, medium="GPU", group=None):
    ev = {"type": "BlockRemoved", "block_hashes": hashes, "medium": medium}
    if group is not None:
        ev["group_idx"] = group
    return ev


def batch(*events):
    # Same shape as vLLM's msgpack-encoded KVEventBatch (array_like).
    return msgpack.unpackb(
        msgpack.packb([1.0, list(events), None]), raw=False, strict_map_key=False
    )


PROMPT = list(range(100, 140))  # 40 tokens
LONG = list(range(200, 248))  # 48 tokens


def test_gpu_prefix_match_uses_token_content_not_engine_hashes():
    idx = KvEventIndex()
    # Engine hashes are opaque: the index must rely on token_ids only.
    idx.apply_batch(
        A, 0, batch(stored([111, 222], None, PROMPT[:32], 16, medium="GPU"))
    )
    m = idx.match([A, B], PROMPT)
    assert m[A] == {MEDIUM_GPU: 32, MEDIUM_CPU: 0}
    assert m[B] == {MEDIUM_GPU: 0, MEDIUM_CPU: 0}
    # A different prompt sharing only the first block matches 16 tokens.
    other = PROMPT[:16] + [7] * 24
    assert idx.match([A], other)[A][MEDIUM_GPU] == 16


def test_parent_chaining_across_events_and_removal():
    idx = KvEventIndex()
    idx.apply_batch(A, 0, batch(stored([b"h1"], None, PROMPT[:16], 16)))
    idx.apply_batch(A, 1, batch(stored([b"h2"], b"h1", PROMPT[16:32], 16)))
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 32
    idx.apply_batch(A, 2, batch(removed([b"h1"])))
    # The first block is gone, so no prefix survives.
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 0


def test_orphan_block_without_known_parent_is_ignored():
    idx = KvEventIndex()
    idx.apply_batch(A, 0, batch(stored([b"h2"], b"unknown", PROMPT[16:32], 16)))
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 0
    assert idx.snapshot()[A]["orphans"] == 1


def test_lmcache_cpu_chunks_with_their_own_block_size():
    idx = KvEventIndex()
    # GPU blocks of 16 tokens and LMCache CPU chunks of 32 tokens coexist.
    idx.apply_batch(A, 0, batch(stored([1], None, PROMPT[:16], 16)))
    idx.apply_batch(
        B, 0, batch(stored([b"c1"], None, PROMPT[:32], 32, medium=MEDIUM_CPU))
    )
    m = idx.match([A, B], PROMPT)
    assert m[A] == {MEDIUM_GPU: 16, MEDIUM_CPU: 0}
    assert m[B] == {MEDIUM_GPU: 0, MEDIUM_CPU: 32}
    idx.apply_batch(B, 1, batch(removed([b"c1"], medium=MEDIUM_CPU)))
    assert idx.match([B], PROMPT)[B][MEDIUM_CPU] == 0


def test_attention_groups_need_every_group():
    idx = KvEventIndex()
    idx.apply_batch(
        A,
        0,
        batch(
            stored([1, 2], None, PROMPT[:32], 16, group=0),
            stored([1], None, PROMPT[:16], 16, group=1),
        ),
    )
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 16


def mamba(hashes, parent, tokens, group=0):
    return stored(hashes, parent, tokens, 8, group=group, kv_cache_spec_kind="mamba")


def attn(hashes, parent, tokens, group=1):
    return stored(
        hashes, parent, tokens, 8, group=group, kv_cache_spec_kind="full_attention"
    )


def test_hybrid_mamba_state_positions():
    """Event shapes captured from Qwen3.8 (3 mamba + 1 attention group) under
    --mamba-cache-mode align: a mamba group stores nothing for the first chunk
    and then one hash, for the last block of a multi-block token span, whose
    parent only the attention group stored."""
    idx = KvEventIndex()
    p = PROMPT  # 40 tokens = 5 blocks of 8
    idx.apply_batch(
        A,
        0,
        batch(
            mamba([], None, p[:24]),
            attn([1, 2, 3], None, p[:24]),
        ),
    )
    # The mamba group holds no state yet: no hybrid hit at all.
    assert idx.match([A], p)[A][MEDIUM_GPU] == 0
    idx.apply_batch(
        A,
        1,
        batch(
            mamba([5], 3, p[24:40]),  # state at the end of block 5 only
            attn([4, 5], 3, p[24:40]),
        ),
    )
    assert idx.snapshot()[A]["orphans"] == 0
    # Hit only where the mamba state exists: 40 tokens, not 24 or 32.
    assert idx.match([A], p)[A][MEDIUM_GPU] == 40
    # A prompt that diverges inside block 5 has attention blocks up to 32 but
    # no mamba state there.
    assert idx.match([A], p[:36] + [1, 2, 3, 4])[A][MEDIUM_GPU] == 0
    # Evicting the mamba state removes the hit; attention blocks remain.
    idx.apply_batch(A, 2, batch(removed([5], group=0)))
    assert idx.match([A], p)[A][MEDIUM_GPU] == 0
    assert idx.snapshot()[A]["gpu_blocks"] == 5


def test_mamba_states_before_their_parent_in_one_batch():
    """Event order captured from Qwen3.8 loading a 4-block prefix from LMCache
    in one step: the three Mamba groups store the state for block 4 (parent =
    block 3) before the attention group stores blocks 1-4 in the same batch.
    The states must not be dropped as orphans."""
    idx = KvEventIndex()
    p = PROMPT[:32]  # 4 blocks of 8
    idx.apply_batch(
        A,
        0,
        batch(
            mamba([4], 3, p[24:32], group=0),
            mamba([4], 3, p[24:32], group=1),
            mamba([4], 3, p[24:32], group=2),
            attn([1, 2, 3, 4], None, p, group=3),
            removed([99], group=3),
        ),
    )
    snap = idx.snapshot()[A]
    assert snap["orphans"] == 0
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 32
    # A parent that never arrives in the batch is still an orphan.
    idx.apply_batch(A, 1, batch(mamba([7], 6, PROMPT[24:32], group=0)))
    assert idx.snapshot()[A]["orphans"] == 1


def test_removal_keeps_parent_while_another_group_holds_it():
    idx = KvEventIndex()
    idx.apply_batch(
        A, 0, batch(attn([1], None, PROMPT[:8]), mamba([1], None, PROMPT[:8]))
    )
    idx.apply_batch(A, 1, batch(removed([1], group=0)))
    # Block 1 is still held by the attention group, so a child resolves.
    idx.apply_batch(A, 2, batch(attn([2], 1, PROMPT[8:16])))
    assert idx.snapshot()[A]["orphans"] == 0


def test_duplicate_store_is_refcounted():
    idx = KvEventIndex()
    ev = stored([1], None, PROMPT[:16], 16)
    idx.apply_batch(A, 0, batch(ev, ev))
    idx.apply_batch(A, 1, batch(removed([1])))
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 16
    idx.apply_batch(A, 2, batch(removed([1])))
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 0


def test_all_blocks_cleared_only_clears_gpu():
    idx = KvEventIndex()
    idx.apply_batch(
        A,
        0,
        batch(
            stored([1], None, PROMPT[:16], 16),
            stored([b"c"], None, PROMPT[:32], 32, medium=MEDIUM_CPU),
            {"type": "AllBlocksCleared"},
        ),
    )
    assert idx.match([A], PROMPT)[A] == {MEDIUM_GPU: 0, MEDIUM_CPU: 32}


def test_sequence_restart_resets_engine():
    idx = KvEventIndex()
    idx.apply_batch(A, 5, batch(stored([1], None, PROMPT[:16], 16)))
    idx.apply_batch(A, 0, batch())
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 0


def test_salted_blocks_are_not_indexed():
    idx = KvEventIndex()
    idx.apply_batch(
        A, 0, batch(stored([1], None, PROMPT[:16], 16, extra_keys=[["salt"]]))
    )
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 0


def test_lora_blocks_do_not_match_base_prompt():
    idx = KvEventIndex()
    idx.apply_batch(A, 0, batch(stored([1], None, PROMPT[:16], 16, lora_name="x")))
    assert idx.match([A], PROMPT)[A][MEDIUM_GPU] == 0


def test_lora_blocks_match_requests_for_that_adapter():
    """vLLM puts the LoRA name first in each block's extra keys; such blocks
    are indexed under the adapter and match only requests for it."""
    idx = KvEventIndex()
    idx.apply_batch(
        A,
        0,
        batch(
            stored(
                [1, 2], None, PROMPT[:32], 16, lora_name="x", extra_keys=[["x"], ["x"]]
            )
        ),
    )
    idx.apply_batch(B, 0, batch(stored([1, 2], None, PROMPT[:32], 16)))
    assert idx.match([A, B], PROMPT, lora_name="x") == {
        A: {MEDIUM_GPU: 32, MEDIUM_CPU: 0},
        B: {MEDIUM_GPU: 0, MEDIUM_CPU: 0},
    }
    assert idx.match([A, B], PROMPT)[A][MEDIUM_GPU] == 0
    assert idx.match([A, B], PROMPT, lora_name="y")[A][MEDIUM_GPU] == 0
    # A LoRA block with further extra keys (here a cache salt) stays out.
    idx.apply_batch(
        A,
        1,
        batch(
            stored([3], None, PROMPT[:16], 16, lora_name="z", extra_keys=[["z", "s"]])
        ),
    )
    assert idx.match([A], PROMPT, lora_name="z")[A][MEDIUM_GPU] == 0


def sliding(hashes, parent, tokens, window, group=0):
    return stored(
        hashes,
        parent,
        tokens,
        8,
        group=group,
        kv_cache_spec_kind="sliding_window",
        kv_cache_spec_sliding_window=window,
    )


def test_sliding_window_needs_every_block_of_its_window():
    """A window of 17 tokens needs cdiv(16, 8) = 2 blocks ending at the hit,
    as vLLM's SlidingWindowManager checks, not just the last one."""
    idx = KvEventIndex()
    p = PROMPT  # 5 blocks of 8
    idx.apply_batch(
        A,
        0,
        batch(
            attn([1, 2, 3, 4, 5], None, p),
            sliding([1, 2, 3, 4, 5], None, p, window=17),
        ),
    )
    assert idx.match([A], p)[A][MEDIUM_GPU] == 40
    # Blocks that slid out of the window are freed.
    idx.apply_batch(A, 1, batch(removed([1, 2, 3], group=0)))
    assert idx.match([A], p)[A][MEDIUM_GPU] == 40
    # With only the last block left, the window ending at 40 is incomplete.
    idx.apply_batch(A, 2, batch(removed([4], group=0)))
    assert idx.match([A], p)[A][MEDIUM_GPU] == 0


def test_reannounced_cpu_chunk_maps_to_its_own_position():
    """LMCache's MP connector leaves out chunks it already announced, from any
    position, but keeps every token and the original parent. A re-stored
    first chunk must map to the first block, not the last."""
    idx = KvEventIndex()
    p = LONG  # 3 chunks of 16
    cpu = dict(medium=MEDIUM_CPU)
    idx.apply_batch(A, 0, batch(stored([b"c1", b"c2", b"c3"], None, p, 16, **cpu)))
    assert idx.match([A], LONG)[A][MEDIUM_CPU] == 48
    idx.apply_batch(A, 1, batch(removed([b"c1"], medium=MEDIUM_CPU)))
    assert idx.match([A], LONG)[A][MEDIUM_CPU] == 0
    # c1 is re-stored while c2 and c3 are still announced.
    idx.apply_batch(A, 2, batch(stored([b"c1"], None, p, 16, **cpu)))
    assert idx.match([A], LONG)[A][MEDIUM_CPU] == 48
    # Removing c1 again drops the first chunk, not the third.
    idx.apply_batch(A, 3, batch(removed([b"c1"], medium=MEDIUM_CPU)))
    assert idx.match([A], LONG)[A][MEDIUM_CPU] == 0
    assert idx.snapshot()[A]["cpu_blocks"] == 2


def test_ambiguous_partial_cpu_store_is_skipped():
    idx = KvEventIndex()
    # Two hashes for three chunks, none of which the index holds.
    idx.apply_batch(
        A, 0, batch(stored([b"x", b"y"], None, LONG, 16, medium=MEDIUM_CPU))
    )
    assert idx.snapshot()[A]["skipped"] == 1
    assert idx.match([A], LONG)[A][MEDIUM_CPU] == 0


def test_untagged_events_are_skipped_with_one_warning():
    idx = KvEventIndex()
    idx.apply_batch(A, 0, batch(["BlockStored", [1], None, PROMPT[:16], 16]))
    idx.apply_batch(A, 1, batch(["BlockStored", [2], None, PROMPT[:16], 16]))
    snap = idx.snapshot()[A]
    assert snap["skipped"] == 2
    assert idx.engine(A).warned_format


def test_prompt_chain_ignores_partial_block():
    assert len(prompt_chain(PROMPT, 16)) == 2


def test_endpoint_from_url():
    assert kv_events_endpoint("http://10.1.2.3:8000", 5557) == "tcp://10.1.2.3:5557"
    assert kv_events_endpoint("http://[fd00::1]:8000", 5557) == "tcp://[fd00::1]:5557"


# --- routing decisions -------------------------------------------------------


def make_router(min_match=1):
    router = KvEventAwareRouter.__new__(KvEventAwareRouter)
    router.session_key = "x-user-id"
    from uhashring import HashRing

    router.hash_ring = HashRing()
    router.min_match_tokens = min_match
    router.tokenize_timeout = 1
    router.tokenize_cooldown = 30
    router._tokenize_failed = {}
    router.index = KvEventIndex()
    router.subscriber = SimpleNamespace(added=[])
    router.subscriber.add_endpoints = router.subscriber.added.append
    router.decisions = {"scored": 0, "balanced": 0, "fallback": 0, "tokenize_error": 0}
    router.balance_abs_threshold = 8
    router.balance_rel_threshold = 1.5
    return router


MODEL_INFO = {
    "m": SimpleNamespace(is_adapter=False),
    "x": SimpleNamespace(is_adapter=True),
}


def endpoints():
    return [
        SimpleNamespace(url=A, model_names=["m", "x"], model_info=MODEL_INFO),
        SimpleNamespace(url=B, model_names=["m", "x"], model_info=MODEL_INFO),
    ]


def request(headers=None):
    return SimpleNamespace(headers=headers or {})


def route(router, body, headers=None, request_stats=None):
    return asyncio.run(
        router.route_request(
            endpoints(), {}, request_stats or {}, request(headers), body
        )
    )


def test_routes_to_engine_with_longest_gpu_prefix():
    router = make_router()
    router.index.apply_batch(B, 0, batch(stored([1, 2], None, PROMPT[:32], 16)))
    router.index.apply_batch(A, 0, batch(stored([9], None, PROMPT[:16], 16)))
    assert route(router, {"prompt": PROMPT}) == B
    assert router.decisions["scored"] == 1


def test_gpu_beats_cpu_at_equal_length_and_load_breaks_ties():
    router = make_router()
    # Shared LMCache server: both engines announce the same CPU chunks.
    for url in (A, B):
        router.index.apply_batch(
            url, 0, batch(stored([b"c"], None, PROMPT[:32], 32, medium=MEDIUM_CPU))
        )
    router.index.apply_batch(A, 1, batch(stored([1, 2], None, PROMPT[:32], 16)))
    assert route(router, {"prompt": PROMPT}) == A

    router = make_router()
    for url in (A, B):
        router.index.apply_batch(
            url, 0, batch(stored([b"c"], None, PROMPT[:32], 32, medium=MEDIUM_CPU))
        )
    stats = {
        A: SimpleNamespace(in_prefill_requests=5, in_decoding_requests=2),
        B: SimpleNamespace(in_prefill_requests=1, in_decoding_requests=0),
    }
    assert route(router, {"prompt": PROMPT}, request_stats=stats) == B


def test_small_load_difference_keeps_cache_affinity():
    """The benchmark failure: a one- or two-request load difference sent
    follow-up turns away from the only engine holding their history."""
    router = make_router()
    router.index.apply_batch(
        A, 0, batch(stored([b"c"], None, PROMPT[:32], 32, medium=MEDIUM_CPU))
    )
    stats = {
        A: SimpleNamespace(in_prefill_requests=1, in_decoding_requests=1),
        B: SimpleNamespace(in_prefill_requests=0, in_decoding_requests=0),
    }
    assert route(router, {"prompt": PROMPT}, request_stats=stats) == A


def test_overloaded_cache_holder_loses_to_idle_engine():
    router = make_router()
    router.index.apply_batch(A, 0, batch(stored([1], None, PROMPT[:16], 16)))
    # A holds 16 of 40 tokens (benefit 0.4) but runs far above the mean.
    stats = {
        A: SimpleNamespace(in_prefill_requests=10, in_decoding_requests=10),
        B: SimpleNamespace(in_prefill_requests=0, in_decoding_requests=0),
    }
    assert route(router, {"prompt": PROMPT}, request_stats=stats) == B
    assert router.decisions["balanced"] == 1
    # Without load, the cache holder wins.
    assert route(router, {"prompt": PROMPT}) == A


def test_exact_ties_are_spread():
    router = make_router()
    for url in (A, B):
        router.index.apply_batch(url, 0, batch(stored([1], None, PROMPT[:16], 16)))
    assert {route(router, {"prompt": PROMPT}) for _ in range(40)} == {A, B}


def test_falls_back_to_session_without_a_hit():
    router = make_router(min_match=16)
    first = route(router, {"prompt": PROMPT}, headers={"x-user-id": "alice"})
    again = route(router, {"prompt": PROMPT}, headers={"x-user-id": "alice"})
    assert first == again
    assert router.decisions["fallback"] == 2


def test_chat_requests_are_tokenized_with_messages():
    body = KvEventAwareRouter._tokenize_body(
        {"messages": [{"role": "user", "content": "hi"}], "tools": [{"t": 1}]}, "m"
    )
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["add_generation_prompt"] is True
    assert body["tools"] == [{"t": 1}]
    assert KvEventAwareRouter._tokenize_body({"prompt": "abc"}, "m") == {
        "model": "m",
        "prompt": "abc",
    }
    assert KvEventAwareRouter._tokenize_body({}, "m") is None


def test_tokenize_body_keeps_prompt_shaping_fields():
    body = KvEventAwareRouter._tokenize_body(
        {"prompt": "abc", "add_special_tokens": False}, "m"
    )
    assert body == {"model": "m", "prompt": "abc", "add_special_tokens": False}
    body = KvEventAwareRouter._tokenize_body(
        {"messages": [], "mm_processor_kwargs": {"a": 1}}, "m"
    )
    assert body["mm_processor_kwargs"] == {"a": 1}


def test_tokenizer_is_least_loaded_engine_without_recent_failure():
    router = make_router()
    eps = endpoints()
    assert router._tokenizer_endpoint(eps, {A: 3, B: 0}).url == B
    router._tokenize_failed[B] = time.time() + 30
    assert router._tokenizer_endpoint(eps, {A: 3, B: 0}).url == A
    # Expired cooldowns are forgotten.
    router._tokenize_failed[B] = time.time() - 1
    assert router._tokenizer_endpoint(eps, {A: 3, B: 0}).url == B
    assert B not in router._tokenize_failed


def test_lora_request_routes_on_adapter_blocks():
    router = make_router()
    router.index.apply_batch(
        A,
        0,
        batch(
            stored(
                [1, 2], None, PROMPT[:32], 16, lora_name="x", extra_keys=[["x"], ["x"]]
            )
        ),
    )
    router.index.apply_batch(B, 0, batch(stored([1], None, PROMPT[:16], 16)))
    assert route(router, {"model": "x", "prompt": PROMPT}) == A
    assert route(router, {"model": "m", "prompt": PROMPT}) == B


def test_request_path_only_adds_subscriptions():
    router = make_router()
    route(router, {"prompt": PROMPT})
    assert router.subscriber.added == [[A, B]]


def test_subscriber_request_path_never_unsubscribes():
    """A request for one model (or a failover retry) lists only some engines;
    it must not drop the other engines' subscriptions and indexes."""
    sub = KvEventSubscriber.__new__(KvEventSubscriber)
    sub.port = 5557
    sub._lock = threading.Lock()
    sub._wanted = {}
    sub.sync_endpoints([A, B])
    sub.add_endpoints([A])
    assert set(sub._wanted) == {A, B}
    sub.add_endpoints(["http://10.0.0.3:8000"])
    assert set(sub._wanted) == {A, B, "http://10.0.0.3:8000"}
    # Discovery is authoritative and does prune.
    sub.sync_endpoints([B])
    assert set(sub._wanted) == {B}


class _FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self, linger=0):
        self.closed = True


def test_engine_missing_from_discovery_keeps_its_index_for_a_grace_period(
    monkeypatch,
):
    """A failed readiness probe or sleep mode must not throw away CPU blocks
    that are never announced again."""
    sub = KvEventSubscriber.__new__(KvEventSubscriber)
    sub.port = 5557
    sub._lock = threading.Lock()
    sub.index = KvEventIndex()
    sub.index.apply_batch(A, 0, batch(stored([1], None, PROMPT[:16], 16)))
    sock = _FakeSocket()
    sub._sockets = {A: sock}
    sub._gone_since = {}
    sub._wanted = {}
    poller = SimpleNamespace(unregister=lambda s: None)
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    sub._reconcile(poller)  # A left discovery
    now[0] += sub.DROP_GRACE_S - 1
    sub._reconcile(poller)
    assert not sock.closed
    assert sub.index.match([A], PROMPT)[A][MEDIUM_GPU] == 16
    # Back before the grace period ends: nothing was lost.
    sub._wanted = {A: kv_events_endpoint(A, 5557)}
    sub._reconcile(poller)
    assert sub._gone_since == {}
    # Gone for longer than the grace period: dropped.
    sub._wanted = {}
    sub._reconcile(poller)
    now[0] += sub.DROP_GRACE_S
    sub._reconcile(poller)
    assert sock.closed
    assert A not in sub._sockets
    assert sub.index.match([A], PROMPT)[A][MEDIUM_GPU] == 0


@pytest.fixture
def clean_routers():
    cleanup_routing_logic()
    yield
    cleanup_routing_logic()


def test_zero_thresholds_are_kept(clean_routers):
    router = initialize_routing_logic(
        RoutingLogic.KVEVENTS,
        kv_events_balance_abs_threshold=0,
        kv_events_balance_rel_threshold=0.0,
    )
    assert router.balance_abs_threshold == 0
    assert router.balance_rel_threshold == 0.0
    assert router.subscriber.port == 5557


def test_dynamic_reconfigure_keeps_kv_events_settings(clean_routers):
    init = DynamicRouterConfig(
        service_discovery="k8s",
        routing_logic="kvevents",
        kv_events_port=6000,
        kv_events_topic="kv",
        kv_events_balance_abs_threshold=0,
    )
    watcher = SimpleNamespace(app=MagicMock(), init_config=init)
    # A config file that does not repeat the kvevents settings keeps the
    # command-line values; one that sets them wins.
    DynamicConfigWatcher.reconfigure_routing_logic(
        watcher,
        DynamicRouterConfig(
            service_discovery="k8s",
            routing_logic="kvevents",
            kv_events_balance_rel_threshold=3.0,
        ),
    )
    router = watcher.app.state.router
    assert router.subscriber.port == 6000
    assert router.subscriber.topic == b"kv"
    assert router.balance_abs_threshold == 0
    assert router.balance_rel_threshold == 3.0


def test_tokenize_failure_falls_back(monkeypatch):
    router = make_router()

    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(router, "_prompt_tokens", boom)
    assert route(router, {"prompt": "x"}) in (A, B)
    assert router.decisions["tokenize_error"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_config_file_mirroring_the_command_line_does_not_reconfigure():
    """from_args fills the kvevents fields with their defaults; a config file
    that leaves them out must still compare equal, or every watch tick would
    rebuild the router and wipe its index."""
    init = DynamicRouterConfig(
        service_discovery="k8s",
        routing_logic="kvevents",
        kv_events_port=5557,
        kv_events_topic="",
        kv_events_min_match_tokens=1,
        kv_events_balance_abs_threshold=8,
        kv_events_balance_rel_threshold=1.5,
    )
    watcher = SimpleNamespace(init_config=init)
    from_file = DynamicRouterConfig(service_discovery="k8s", routing_logic="kvevents")
    assert from_file != init
    assert DynamicConfigWatcher.with_startup_kv_events(watcher, from_file) == init


def test_reconfigure_keeps_the_live_index(clean_routers):
    router = initialize_routing_logic(RoutingLogic.KVEVENTS, kv_events_port=5557)
    router.index.apply_batch(A, 0, batch(stored([1], None, PROMPT[:16], 16)))
    subscriber = router.subscriber

    same = reconfigure_routing_logic(
        RoutingLogic.KVEVENTS, kv_events_port=5557, kv_events_balance_abs_threshold=2
    )
    assert same is not router
    assert same.balance_abs_threshold == 2
    assert same.subscriber is subscriber
    assert same.index.match([A], PROMPT)[A][MEDIUM_GPU] == 16
    assert subscriber._thread.is_alive()

    other = reconfigure_routing_logic(RoutingLogic.KVEVENTS, kv_events_port=6000)
    assert other.subscriber is not subscriber
    assert other.index.match([A], PROMPT)[A][MEDIUM_GPU] == 0
    assert not subscriber._thread.is_alive()
