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

_finished_reqs: set[str] = set()
_run_proxy = True
_zmq_ctx = zmq.asyncio.Context()
_zmq_task = None


async def _zmq_pull_server(proxy_host: str = "0.0.0.0", proxy_port: int = 7500):
    """ZMQ PULL server that receives KV transfer completion notifications."""
    try:
        socket = _zmq_ctx.socket(zmq.PULL)
        proxy_url = f"{proxy_host}:{proxy_port}"
        socket.bind(f"tcp://{proxy_url}")
        logger.info(f"ZMQ proxy server started on {proxy_url}")
    except Exception as e:
        logger.error(f"Failed to bind ZMQ socket to {proxy_url}: {e}")
        socket.close()
        return

    while _run_proxy:
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
            _finished_reqs.add(req_id)
            logger.info(f"Prefill of req {req_id} done.")
        except zmq.Again:
            await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"ZMQ Error in message processing: {e}")
            # Don't break — continue processing messages
            await asyncio.sleep(0.1)

    socket.close()
    logger.info("ZMQ PULL server stopped.")


async def start_zmq_task(proxy_host: str = "0.0.0.0", proxy_port: int = 7500):
    """Start the ZMQ pull server task."""
    global _zmq_task
    if _zmq_task is None:
        _zmq_task = asyncio.create_task(_zmq_pull_server(proxy_host, proxy_port))
        logger.info("ZMQ task started")
        await asyncio.sleep(0.1)


async def stop_zmq_task():
    """Stop the ZMQ pull server task."""
    global _zmq_task, _run_proxy
    if _zmq_task is not None:
        _run_proxy = False
        _zmq_task.cancel()
        try:
            await _zmq_task
        except asyncio.CancelledError:
            pass
        _zmq_task = None
        logger.info("ZMQ task stopped")


async def wait_decode_kv_ready(req_id: str, timeout: float = 10.0):
    """Wait for ZMQ notification that KV transfer is done, with timeout.

    If timeout expires, proceed anyway — decode will fallback to recompute
    via kv_load_failure_policy='recompute'.
    """
    start = time.time()
    while req_id not in _finished_reqs:
        if time.time() - start > timeout:
            logger.warning(
                f"Timeout ({timeout}s) waiting for KV ready signal for req"
                f" {req_id}. Proceeding to decode (will recompute if KV not"
                " available)."
            )
            return
        await asyncio.sleep(0.001)
    logger.info(f"Prefill node signaled kv ready for req {req_id}")
    _finished_reqs.discard(req_id)
