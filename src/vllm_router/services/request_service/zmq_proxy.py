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

"""ZMQ proxy server for PD disaggregated prefill KV transfer notifications."""

import asyncio
import time
from dataclasses import dataclass

import msgspec
import zmq
import zmq.asyncio

from vllm_router.log import init_logger

try:
    from lmcache.v1.storage_backend.connector.nixl_connector_v3 import (
        NixlMsg,
    )
except ImportError:
    try:
        from lmcache.v1.storage_backend.pd_backend import ProxyNotif as NixlMsg
    except ImportError:

        class NixlMsg(msgspec.Struct):
            req_id: str


logger = init_logger(__name__)


@dataclass
class NixlConfig:
    """NIXL-specific configuration for disaggregated prefill routing."""

    proxy_host: str
    proxy_port: int
    peer_host: str
    peer_init_port: int
    peer_alloc_port: int
    finished_req_ttl: float = 120.0
    cleanup_interval: float = 60.0


class ZmqProxy:
    """Manages a ZMQ PULL server for KV transfer completion notifications."""

    def __init__(
        self,
        finished_req_ttl: float = 120.0,
        cleanup_interval: float = 60.0,
    ):
        """
        Args:
            finished_req_ttl: Seconds to keep a KV-ready entry before evicting
                it. Should be at least as long as the longest expected decode
                latency so that a slow decoder can still find its entry.
                Defaults to 120 s (2× a typical 60 s worst-case decode).
            cleanup_interval: How often the background cleanup task runs.
                Defaults to 60 s; tune down if memory is a concern.
        """
        self._pending: dict[str, asyncio.Event] = {}
        self._finished_ts: dict[str, float] = {}
        self._finished_req_ttl = finished_req_ttl
        self._cleanup_interval = cleanup_interval
        self._run_proxy: bool = True
        self._zmq_ctx = zmq.asyncio.Context()
        self._task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None

    async def _pull_server(self, proxy_host: str, proxy_port: int):
        """ZMQ PULL server that receives KV transfer completion notifications."""
        try:
            socket = self._zmq_ctx.socket(zmq.PULL)
            proxy_url = f"{proxy_host}:{proxy_port}"
            socket.bind(f"tcp://{proxy_url}")
            logger.info(f"ZMQ proxy server started on {proxy_url}")
        except Exception as e:
            logger.error(f"Failed to bind ZMQ socket to {proxy_url}: {e}")
            socket.close()
            return

        while self._run_proxy:
            try:
                msg_bytes = await socket.recv()
                # Decode without strict type checking — LMCache may send
                # ProxyNotif while router expects NixlMsg. Both have req_id.
                try:
                    msg = msgspec.msgpack.decode(msg_bytes, type=NixlMsg)
                except Exception:
                    # Fallback: decode as generic dict
                    msg_dict = msgspec.msgpack.decode(msg_bytes)
                    if isinstance(msg_dict, dict) and "req_id" in msg_dict:
                        msg = type("Msg", (), {"req_id": msg_dict["req_id"]})()
                    else:
                        logger.warning(f"ZMQ: unknown message format: {msg_dict}")
                        continue
                req_id = msg.req_id
                self._finished_ts[req_id] = time.time()
                # Wake up any coroutine waiting on this request.
                event = self._pending.get(req_id)
                if event is not None:
                    event.set()
                logger.debug(f"Prefill of req {req_id} done.")
            except zmq.Again:
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"ZMQ Error in message processing: {e}")
                # Don't break — continue processing messages
                await asyncio.sleep(0.1)

        socket.close()
        logger.info("ZMQ PULL server stopped.")

    async def _cleanup_loop(self):
        """Periodically evict stale entries from _finished_ts and _pending."""
        while self._run_proxy:
            await asyncio.sleep(self._cleanup_interval)
            now = time.time()
            stale = [
                req_id
                for req_id, ts in self._finished_ts.items()
                if now - ts > self._finished_req_ttl
            ]
            for req_id in stale:
                del self._finished_ts[req_id]
                self._pending.pop(req_id, None)
            if stale:
                logger.debug(f"ZMQ cleanup: evicted {len(stale)} stale req entries.")

    async def start(self, proxy_host: str = "0.0.0.0", proxy_port: int = 7500):
        """Start the ZMQ pull server task."""
        if self._task is None:
            self._task = asyncio.create_task(self._pull_server(proxy_host, proxy_port))
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("ZMQ task started")
            await asyncio.sleep(0.1)

    async def stop(self):
        """Stop the ZMQ pull server task."""
        if self._task is not None:
            self._run_proxy = False
            self._task.cancel()
            if self._cleanup_task is not None:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                self._cleanup_task = None
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("ZMQ task stopped")

    async def wait_kv_ready(self, req_id: str, timeout: float = 10.0):
        """Wait for ZMQ notification that KV transfer is done, with timeout.

        Suspends the coroutine until the prefill node signals completion via
        an asyncio.Event, avoiding a busy-wait loop.  If timeout expires,
        proceed anyway — decode will fallback to recompute via
        kv_load_failure_policy='recompute'.
        """
        # If the signal already arrived before we start waiting, skip the wait.
        if req_id not in self._finished_ts:
            event = self._pending.setdefault(req_id, asyncio.Event())
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Timeout ({timeout}s) waiting for KV ready signal for req"
                    f" {req_id}. Proceeding to decode (will recompute if KV"
                    " not available)."
                )
                return
            finally:
                self._pending.pop(req_id, None)

        logger.debug(f"Prefill node signaled kv ready for req {req_id}")
        self._finished_ts.pop(req_id, None)
