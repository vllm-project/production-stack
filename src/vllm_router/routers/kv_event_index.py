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
"""Index of cached KV blocks per engine, built from vLLM KV cache events.

vLLM publishes ``BlockStored`` / ``BlockRemoved`` / ``AllBlocksCleared``
events over a ZMQ PUB socket when started with ``--kv-events-config``. GPU
prefix-cache blocks are published by vLLM itself (``medium="GPU"``). With
LMCache multiprocess mode (LMCache >= 0.5.6), the MP connector republishes the
cache server's store and eviction log as ``medium="CPU"`` events.

The two sources hash blocks differently (vLLM block hashes vs. LMCache chunk
hashes) and use different block sizes, so engine-side hashes cannot be compared
with anything the router computes. Every ``BlockStored`` event carries its
``token_ids``, though, so the index re-keys each block by a chained hash of its
token content that the router can reproduce from a request's prompt tokens.
Engine hashes are kept only to resolve parents and removals.
"""

import math
import threading
import time
from array import array
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import xxhash

from vllm_router.log import init_logger

logger = init_logger(__name__)

try:
    import msgpack
    import zmq
except ImportError:  # pragma: no cover - checked when the router is built
    msgpack = None
    zmq = None


MEDIUM_GPU = "GPU"
MEDIUM_CPU = "CPU"

# Chain seed for the first block of a prompt. Mixed with the LoRA name so that
# blocks cached for different adapters never alias.
_ROOT_SEED = 0x9E3779B97F4A7C15

# (medium, group_idx, block_size): one hash chain namespace per tier, KV cache
# group and block granularity.
Namespace = Tuple[str, Optional[int], int]


def _root_hash(lora_name: Optional[str]) -> int:
    if not lora_name:
        return _ROOT_SEED
    return xxhash.xxh3_64_intdigest(lora_name.encode("utf-8"), seed=_ROOT_SEED)


def chain_hash(parent: int, token_ids: Iterable[int]) -> int:
    """Hash one block's tokens chained to its parent block's hash."""
    data = array("q", token_ids).tobytes()
    return xxhash.xxh3_64_intdigest(data, seed=parent)


def prompt_chain(
    token_ids: List[int], block_size: int, lora_name: Optional[str] = None
) -> List[int]:
    """Chained hashes of every full block of ``token_ids``."""
    hashes = []
    parent = _root_hash(lora_name)
    for start in range(0, len(token_ids) - block_size + 1, block_size):
        parent = chain_hash(parent, token_ids[start : start + block_size])
        hashes.append(parent)
    return hashes


# KV cache spec kinds whose blocks hold a state *at* a position (Mamba / linear
# attention) or only a trailing window, rather than one entry per block of the
# prefix. A cache hit of length L needs their entry for the block ending at L;
# sliding-window groups with a known window need every block of the window
# ending at L (see ``EngineIndex.match``).
_POSITIONAL_KIND_MARKERS = ("mamba", "sliding", "local", "linear")


def _is_positional(kind: Optional[str]) -> bool:
    return bool(kind) and any(m in kind.lower() for m in _POSITIONAL_KIND_MARKERS)


def _window_blocks(kind: Optional[str], window: Optional[int], block_size: int) -> int:
    """Blocks a sliding-window group needs ending at a hit, as vLLM's
    SlidingWindowManager counts them (cdiv(window - 1, block_size)); 0 when
    the group is not a sliding window of known size."""
    if not kind or "sliding" not in kind.lower() or not window or window <= 1:
        return 0
    return max(1, math.ceil((window - 1) / block_size))


def _strip_lora_keys(
    extra_keys: Optional[List[Any]], lora_name: Optional[str]
) -> Optional[List[Any]]:
    """Drop the LoRA name vLLM puts first in each block's extra keys.

    The LoRA name is already folded into the chain root, so blocks whose only
    extra key is the adapter name stay indexable."""
    if not extra_keys or not lora_name:
        return extra_keys
    out = []
    for keys in extra_keys:
        if keys and keys[0] == lora_name:
            keys = keys[1:]
        out.append(keys)
    return out


@dataclass
class _BlockRef:
    namespace: Namespace
    chain: int
    parent_key: Tuple[str, int, Any]
    count: int = 1


@dataclass
class EngineIndex:
    """Cached blocks of one engine, keyed by content-chain hash."""

    # namespace -> chain hash -> number of engine blocks holding it
    blocks: Dict[Namespace, Dict[int, int]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    # (medium, group_idx, engine block hash) -> block reference, for removals
    by_engine_hash: Dict[Tuple[str, Optional[int], Any], _BlockRef] = field(
        default_factory=dict
    )
    # (medium, block_size, engine block hash) -> [chain hash, references].
    # vLLM hashes a block the same way in every KV cache group of a given block
    # size, so a group that stores only some blocks (Mamba) resolves its parent
    # through the blocks another group (full attention) stored.
    parents: Dict[Tuple[str, int, Any], List[int]] = field(default_factory=dict)
    # (medium, group_idx) -> KV cache spec kind announced by the engine
    group_kinds: Dict[Tuple[str, Optional[int]], Optional[str]] = field(
        default_factory=dict
    )
    # (medium, group_idx) -> sliding window in tokens, for sliding-window groups
    group_windows: Dict[Tuple[str, Optional[int]], Optional[int]] = field(
        default_factory=dict
    )
    last_seq: Optional[int] = None
    stored: int = 0
    removed: int = 0
    orphans: int = 0
    skipped: int = 0
    gaps: int = 0
    warned_format: bool = False

    def num_blocks(self, medium: Optional[str] = None) -> int:
        return sum(
            len(chains)
            for ns, chains in self.blocks.items()
            if medium is None or ns[0] == medium
        )

    def clear(self, medium: Optional[str] = None) -> None:
        def hit(key) -> bool:
            return medium is None or key[0] == medium

        for d in (
            self.blocks,
            self.by_engine_hash,
            self.parents,
            self.group_kinds,
            self.group_windows,
        ):
            for key in [k for k in d if hit(k)]:
                del d[key]

    def _add(self, ns: Namespace, chain: int) -> None:
        chains = self.blocks[ns]
        chains[chain] = chains.get(chain, 0) + 1

    def _drop(self, ref: _BlockRef) -> None:
        chains = self.blocks.get(ref.namespace)
        if chains is not None:
            left = chains.get(ref.chain, 0) - 1
            if left > 0:
                chains[ref.chain] = left
            else:
                chains.pop(ref.chain, None)
        parent = self.parents.get(ref.parent_key)
        if parent is not None:
            parent[1] -= 1
            if parent[1] <= 0:
                del self.parents[ref.parent_key]

    def apply_stored(self, event: Dict[str, Any], count_orphan: bool = True) -> bool:
        """Index one BlockStored event. Returns False when its parent is not
        indexed (an orphan), so the caller can retry it later in the batch;
        ``count_orphan=False`` leaves the orphan counter to that caller."""
        medium = event.get("medium") or MEDIUM_GPU
        group = event.get("group_idx")
        block_size = int(event.get("block_size") or 0)
        block_hashes = event.get("block_hashes") or []
        token_ids = event.get("token_ids") or []
        if block_size <= 0:
            self.skipped += 1
            return True
        self.group_kinds[(medium, group)] = event.get("kv_cache_spec_kind")
        self.group_windows[(medium, group)] = event.get("kv_cache_spec_sliding_window")
        if not block_hashes:
            # A group that cached nothing for these tokens (e.g. a Mamba group
            # between its aligned state positions).
            return True
        num_blocks = len(token_ids) // block_size
        if num_blocks < len(block_hashes):
            # Not enough tokens to rebuild every block's content.
            self.skipped += 1
            return True
        lora_name = event.get("lora_name")
        extra_keys = _strip_lora_keys(event.get("extra_keys"), lora_name)
        if extra_keys and any(extra_keys):
            # Multimodal / cache-salted / prompt-embedding blocks: the router
            # cannot rebuild their key from token ids alone.
            self.skipped += 1
            return True

        parent_hash = event.get("parent_block_hash")
        if parent_hash is None:
            chain = _root_hash(lora_name)
        else:
            parent = self.parents.get((medium, block_size, parent_hash))
            if parent is None:
                # The parent was never seen (subscribed late, or lost events):
                # this block cannot be placed in a prefix chain.
                if count_orphan:
                    self.orphans += 1
                return False
            chain = parent[0]

        chains = []
        for b in range(num_blocks):
            chain = chain_hash(chain, token_ids[b * block_size : (b + 1) * block_size])
            chains.append(chain)

        # token_ids span num_blocks blocks. Groups that store a state only at
        # the end (Mamba) send the hashes of the last len(block_hashes) blocks.
        ns: Namespace = (medium, group, block_size)
        positions = list(range(num_blocks - len(block_hashes), num_blocks))
        if len(block_hashes) < num_blocks and not _is_positional(
            self.group_kinds.get((medium, group))
        ):
            # Groups that store every block (attention, LMCache CPU chunks)
            # send one hash per block, except that LMCache's MP connector
            # leaves out chunks it has already announced, from any position,
            # while keeping all token_ids and the original parent. The hashes
            # then belong to the blocks this index does not hold yet, in order.
            known = self.blocks.get(ns, {})
            positions = [b for b in range(num_blocks) if chains[b] not in known]
            if len(positions) != len(block_hashes):
                # Cannot tell which block each hash belongs to.
                self.skipped += 1
                return True

        for engine_hash, b in zip(block_hashes, positions):
            chain = chains[b]
            key = (medium, group, engine_hash)
            ref = self.by_engine_hash.get(key)
            if ref is not None:
                ref.count += 1
                continue
            parent_key = (medium, block_size, engine_hash)
            self.by_engine_hash[key] = _BlockRef(ns, chain, parent_key)
            self._add(ns, chain)
            parent = self.parents.get(parent_key)
            if parent is None:
                self.parents[parent_key] = [chain, 1]
            else:
                parent[1] += 1
            self.stored += 1
        return True

    def apply_removed(self, event: Dict[str, Any]) -> None:
        medium = event.get("medium") or MEDIUM_GPU
        group = event.get("group_idx")
        for engine_hash in event.get("block_hashes") or []:
            key = (medium, group, engine_hash)
            ref = self.by_engine_hash.get(key)
            if ref is None:
                continue
            ref.count -= 1
            if ref.count <= 0:
                del self.by_engine_hash[key]
                self._drop(ref)
            self.removed += 1

    def match(
        self, chains_by_size: Dict[int, List[int]], medium: str
    ) -> Tuple[int, Dict[Optional[int], int]]:
        """Longest reusable cached prefix, in tokens, on one medium.

        A prefix of L tokens is reusable only if every KV cache group the
        engine runs can serve it: attention groups need every block up to L,
        Mamba / sliding-window groups need their entry for the block ending at
        L, or every block of their window ending at L when the window is known.
        Each group yields the set of lengths it can serve; the answer is the
        longest length all groups share.
        """
        valid: Dict[Optional[int], set] = {}
        for (ns_medium, group), kind in self.group_kinds.items():
            if ns_medium == medium:
                valid[group] = set()
        for (ns_medium, group, block_size), chains in self.blocks.items():
            if ns_medium != medium:
                continue
            prompt = chains_by_size.get(block_size)
            if not prompt or not chains:
                continue
            lengths = valid.setdefault(group, set())
            kind = self.group_kinds.get((medium, group))
            need = _window_blocks(
                kind, self.group_windows.get((medium, group)), block_size
            )
            if need:
                run = 0
                for i, h in enumerate(prompt):
                    run = run + 1 if h in chains else 0
                    if run >= min(need, i + 1):
                        lengths.add((i + 1) * block_size)
            elif _is_positional(kind):
                lengths.update(
                    (i + 1) * block_size for i, h in enumerate(prompt) if h in chains
                )
            else:
                for i, h in enumerate(prompt):
                    if h not in chains:
                        break
                    lengths.add((i + 1) * block_size)
        per_group = {g: max(v, default=0) for g, v in valid.items()}
        if not valid:
            return 0, per_group
        common = set.intersection(*valid.values())
        return max(common, default=0), per_group


class KvEventIndex:
    """Thread-safe per-engine index, fed by ``KvEventSubscriber``."""

    def __init__(self):
        self._lock = threading.Lock()
        self._engines: Dict[str, EngineIndex] = {}

    def engine(self, url: str) -> EngineIndex:
        idx = self._engines.get(url)
        if idx is None:
            idx = self._engines[url] = EngineIndex()
        return idx

    def drop_engine(self, url: str) -> None:
        with self._lock:
            self._engines.pop(url, None)

    def block_sizes(self) -> List[int]:
        with self._lock:
            return sorted(
                {ns[2] for idx in self._engines.values() for ns in idx.blocks}
            )

    def apply_batch(self, url: str, seq: Optional[int], batch: Any) -> None:
        """Apply one decoded ``KVEventBatch`` ([ts, events, dp_rank])."""
        if isinstance(batch, dict):
            events = batch.get("events") or []
        else:
            events = batch[1] if len(batch) > 1 else []
        with self._lock:
            idx = self.engine(url)
            if seq is not None:
                if idx.last_seq is not None and seq <= idx.last_seq:
                    # Sequence restarted: the publisher (engine) restarted and
                    # its GPU cache is empty. CPU placements are re-announced.
                    logger.info(
                        f"KV event sequence restarted for {url} "
                        f"({idx.last_seq} -> {seq}); resetting its index"
                    )
                    idx.clear()
                elif idx.last_seq is not None and seq != idx.last_seq + 1:
                    # Lost batches are not replayed: a missed BlockRemoved
                    # leaves a stale entry until the block is stored again or
                    # the engine restarts. Clearing would also drop CPU blocks,
                    # which are announced only once, so only count the gap.
                    idx.gaps += 1
                    logger.warning(
                        f"KV event gap for {url}: expected seq "
                        f"{idx.last_seq + 1}, got {seq}"
                    )
                idx.last_seq = seq
        # One event at a time, so that the request path's match() never waits
        # for a whole batch of token hashing.
        pending: List[Dict[str, Any]] = []
        for event in events:
            with self._lock:
                self._apply_event(idx, event, pending)
        if pending:
            with self._lock:
                idx.orphans += len(pending)

    @staticmethod
    def _store(idx: EngineIndex, event: Dict[str, Any], pending: List) -> None:
        """Store one block event, retrying parked orphans once it lands.

        Within one batch vLLM can store a block before its parent: when an
        engine loads a prefix from LMCache in one step, the Mamba groups'
        states (parent = the previous attention block) come before the
        attention group's event that stores that parent. Such events are
        parked and retried after every later store in the batch; whatever is
        still unresolved at the end of the batch is an orphan."""
        if not idx.apply_stored(event, count_orphan=False):
            pending.append(event)
            return
        progress = True
        while progress and pending:
            progress = False
            for parked in list(pending):
                if idx.apply_stored(parked, count_orphan=False):
                    pending.remove(parked)
                    progress = True

    @staticmethod
    def _apply_event(
        idx: EngineIndex, event: Any, pending: Optional[List] = None
    ) -> None:
        if not isinstance(event, dict):
            # vLLM tags events as maps ({"type": "BlockStored", ...}). Older
            # releases encoded them as arrays, which carry no field names.
            if not idx.warned_format:
                idx.warned_format = True
                logger.warning(
                    "Ignoring KV events that are not tagged maps "
                    f"({type(event).__name__}); the engine's vLLM encodes events "
                    "in a format the kvevents router does not decode"
                )
            idx.skipped += 1
            return
        kind = event.get("type")
        if kind == "BlockStored":
            if pending is None:
                idx.apply_stored(event)
            else:
                KvEventIndex._store(idx, event, pending)
        elif kind == "BlockRemoved":
            idx.apply_removed(event)
        elif kind == "AllBlocksCleared":
            # vLLM emits this when its prefix cache is reset; it carries no
            # medium and concerns only the GPU cache.
            idx.clear(MEDIUM_GPU)
        else:
            idx.skipped += 1

    def match(
        self,
        urls: Iterable[str],
        token_ids: List[int],
        lora_name: Optional[str] = None,
    ) -> Dict[str, Dict[str, int]]:
        """Cached-prefix length per engine and medium for a prompt, run on the
        base model or, with ``lora_name``, on that LoRA adapter."""
        sizes = self.block_sizes()
        chains_by_size = {bs: prompt_chain(token_ids, bs, lora_name) for bs in sizes}
        result: Dict[str, Dict[str, int]] = {}
        with self._lock:
            for url in urls:
                idx = self._engines.get(url)
                if idx is None:
                    result[url] = {MEDIUM_GPU: 0, MEDIUM_CPU: 0}
                    continue
                result[url] = {
                    MEDIUM_GPU: idx.match(chains_by_size, MEDIUM_GPU)[0],
                    MEDIUM_CPU: idx.match(chains_by_size, MEDIUM_CPU)[0],
                }
        return result

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                url: {
                    "gpu_blocks": idx.num_blocks(MEDIUM_GPU),
                    "cpu_blocks": idx.num_blocks(MEDIUM_CPU),
                    "namespaces": sorted(
                        [list(ns) for ns, c in idx.blocks.items() if c],
                        key=str,
                    ),
                    "group_kinds": {
                        f"{m}/{g}": k for (m, g), k in idx.group_kinds.items()
                    },
                    "stored": idx.stored,
                    "removed": idx.removed,
                    "orphans": idx.orphans,
                    "skipped": idx.skipped,
                    "gaps": idx.gaps,
                    "last_seq": idx.last_seq,
                }
                for url, idx in self._engines.items()
            }


def kv_events_endpoint(url: str, port: int) -> str:
    """ZMQ endpoint of an engine's KV event publisher, from its HTTP URL."""
    host = urlparse(url).hostname
    if host and ":" in host:
        host = f"[{host}]"
    return f"tcp://{host}:{port}"


class KvEventSubscriber:
    """Subscribes to every engine's KV event publisher on one thread.

    Service discovery owns the engine set (``sync_endpoints``, polled every
    ``DISCOVERY_INTERVAL_S``), so engines come and go with it. The request
    path only adds engines discovery has not reported yet (``add_endpoints``):
    a request sees just the engines of its model, or only the remaining ones on
    a failover retry, and must not unsubscribe the others.
    """

    POLL_TIMEOUT_MS = 200
    DISCOVERY_INTERVAL_S = 2.0
    SUMMARY_INTERVAL_S = 30.0
    # How long an engine may be missing from discovery (a failed readiness
    # probe, sleep mode) before its subscription and index are dropped. CPU
    # blocks are announced only once, so a dropped index cannot be rebuilt.
    DROP_GRACE_S = 60.0

    def __init__(
        self,
        index: KvEventIndex,
        port: int,
        topic: str = "",
        endpoint_provider: Optional[Callable[[], Iterable[str]]] = None,
    ):
        if zmq is None or msgpack is None:
            raise ImportError(
                "KV event routing requires the 'pyzmq' and 'msgpack' packages "
                "(router dependencies); install them in the router environment"
            )
        self.index = index
        self.endpoint_provider = endpoint_provider
        self.port = port
        self.topic = topic.encode("utf-8")
        self._ctx = zmq.Context.instance()
        self._lock = threading.Lock()
        self._wanted: Dict[str, str] = {}
        self._sockets: Dict[str, Any] = {}
        self._gone_since: Dict[str, float] = {}
        self._stop = threading.Event()
        self._last_discovery = 0.0
        self._last_summary = 0.0
        self._last_summary_state: Optional[Dict[str, Any]] = None
        self._thread = threading.Thread(
            target=self._run, name="kv-event-subscriber", daemon=True
        )
        self._thread.start()
        self.last_sync = 0.0

    def sync_endpoints(self, urls: Iterable[str]) -> None:
        """Subscribe to exactly ``urls`` (the full discovered engine set)."""
        wanted = {url: kv_events_endpoint(url, self.port) for url in urls}
        with self._lock:
            if wanted.keys() != self._wanted.keys():
                self._wanted = wanted
        self.last_sync = time.time()

    def add_endpoints(self, urls: Iterable[str]) -> None:
        """Subscribe to any of ``urls`` not subscribed yet; never unsubscribe."""
        with self._lock:
            for url in urls:
                if url not in self._wanted:
                    self._wanted[url] = kv_events_endpoint(url, self.port)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _reconcile(self, poller: Any) -> None:
        with self._lock:
            wanted = dict(self._wanted)
        now = time.time()
        for url in list(self._sockets):
            if url in wanted:
                self._gone_since.pop(url, None)
                continue
            # Not routed to while missing; keep listening for a grace period.
            gone = self._gone_since.setdefault(url, now)
            if now - gone < self.DROP_GRACE_S:
                continue
            del self._gone_since[url]
            sock = self._sockets.pop(url)
            poller.unregister(sock)
            sock.close(linger=0)
            self.index.drop_engine(url)
            logger.info(
                f"Stopped KV event subscription for {url} "
                f"(not discovered for {self.DROP_GRACE_S:.0f} s)"
            )
        for url, endpoint in wanted.items():
            if url in self._sockets:
                continue
            sock = self._ctx.socket(zmq.SUB)
            sock.setsockopt(zmq.SUBSCRIBE, self.topic)
            sock.setsockopt(zmq.RCVHWM, 0)
            sock.connect(endpoint)
            poller.register(sock, zmq.POLLIN)
            self._sockets[url] = sock
            logger.info(f"Subscribed to KV events of {url} at {endpoint}")

    def _discover(self) -> None:
        """Follow service discovery so events are captured before the first
        request reaches an engine."""
        now = time.time()
        if (
            self.endpoint_provider is None
            or now - self._last_discovery < self.DISCOVERY_INTERVAL_S
        ):
            return
        self._last_discovery = now
        try:
            urls = list(self.endpoint_provider())
        except Exception as e:  # service discovery not initialized yet
            logger.debug(f"KV event subscriber cannot list endpoints yet: {e}")
            return
        self.sync_endpoints(urls)

    def _log_summary(self) -> None:
        now = time.time()
        if now - self._last_summary < self.SUMMARY_INTERVAL_S:
            return
        self._last_summary = now
        state = {
            url: (s["gpu_blocks"], s["cpu_blocks"], s["orphans"], s["gaps"])
            for url, s in self.index.snapshot().items()
        }
        if state != self._last_summary_state:
            self._last_summary_state = state
            logger.info(
                "KV event index (gpu_blocks, cpu_blocks, orphans, gaps): " f"{state}"
            )

    def _run(self) -> None:
        poller = zmq.Poller()
        while not self._stop.is_set():
            try:
                self._discover()
                self._log_summary()
                self._reconcile(poller)
                if not self._sockets:
                    time.sleep(self.POLL_TIMEOUT_MS / 1000)
                    continue
                ready = dict(poller.poll(self.POLL_TIMEOUT_MS))
                for url, sock in list(self._sockets.items()):
                    if sock not in ready:
                        continue
                    while True:
                        try:
                            frames = sock.recv_multipart(zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        self._handle(url, frames)
            except Exception as e:  # keep the subscriber alive
                logger.exception(f"KV event subscriber error: {e}")
                time.sleep(1)
        for sock in self._sockets.values():
            sock.close(linger=0)

    def _handle(self, url: str, frames: List[bytes]) -> None:
        # vLLM's ZmqEventPublisher sends (topic, seq as 8-byte big-endian,
        # msgpack payload).
        if not frames:
            return
        if len(frames) == 3:
            _, seq_bytes, payload = frames
            seq = int.from_bytes(seq_bytes, "big")
        elif len(frames) == 2:
            seq, payload = None, frames[1]
        else:
            seq, payload = None, frames[-1]
        try:
            batch = msgpack.unpackb(payload, raw=False, strict_map_key=False)
        except Exception as e:
            logger.warning(f"Undecodable KV event batch from {url}: {e}")
            return
        self.index.apply_batch(url, seq, batch)
