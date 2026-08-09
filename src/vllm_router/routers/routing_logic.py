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

import abc
import asyncio
import concurrent.futures
import enum
import math
import os
import random
import threading
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, Request

try:
    from transformers import AutoTokenizer
except ImportError:
    pass

try:
    from lmcache.v1.cache_controller import controller_manager
    from lmcache.v1.cache_controller.message import (
        LookupMsg,
        QueryInstMsg,
    )
except ImportError:
    pass
from uhashring import HashRing

from vllm_router.log import init_logger
from vllm_router.service_discovery import EndpointInfo
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats
from vllm_router.utils import SingletonABCMeta

logger = init_logger(__name__)


class RoutingLogic(str, enum.Enum):
    ROUND_ROBIN = "roundrobin"
    SESSION_BASED = "session"
    KVAWARE = "kvaware"
    LOADAWARE = "loadaware"
    PREFIXAWARE = "prefixaware"
    DISAGGREGATED_PREFILL = "disaggregated_prefill"
    DISAGGREGATED_PREFILL_ORCHESTRATED = "disaggregated_prefill_orchestrated"


# The single tunable of the `loadaware` routing logic. beta = 1.0 reads as: an
# endpoint sitting 100% above fleet-average load is docked one full cache hit's
# worth of preference. That statement mentions no hardware, model, request rate
# or fleet size, which is what makes it a defensible default rather than a
# number calibrated on one cluster.
#
# There is no second weight on the benefit term: an argmax is invariant under
# positive scaling, so only the ratio of two weights would matter anyway.
DEFAULT_LOADAWARE_BETA = 1.0


def _loadaware_beta(override: Optional[float]) -> float:
    """Resolve the loadaware beta: explicit value > LOADAWARE_BETA env > default.

    The environment fallback lets the weight be adjusted on a running
    deployment without changing the router's command line.
    """
    if override is not None:
        return float(override)
    raw = os.environ.get("LOADAWARE_BETA")
    if raw is None or raw.strip() == "":
        return DEFAULT_LOADAWARE_BETA
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            f"Ignoring non-numeric LOADAWARE_BETA={raw!r}, "
            f"using {DEFAULT_LOADAWARE_BETA}"
        )
        return DEFAULT_LOADAWARE_BETA


class RoutingInterface(metaclass=SingletonABCMeta):
    def _qps_routing(
        self, endpoints: List[EndpointInfo], request_stats: Dict[str, RequestStats]
    ) -> str:
        """
        Route the request to the appropriate engine URL based on the QPS of
        each engine

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
        """
        lowest_qps = float("inf")
        ret = None
        for info in endpoints:
            url = info.url
            if url not in request_stats:
                return url  # This engine does not have any requests
            request_stat = request_stats[url]
            if request_stat.qps < lowest_qps:
                lowest_qps = request_stat.qps
                ret = url
        return ret

    def _update_hash_ring(self, endpoints: List["EndpointInfo"]):
        """
        Update the hash ring with the current list of endpoints.
        """
        # Extract endpoint URLs
        endpoint_urls = [endpoint.url for endpoint in endpoints]

        # Get the current nodes in the hash ring
        current_nodes = set(self.hash_ring.get_nodes())

        # Convert the new endpoint URLs to a set for easy comparison
        new_nodes = set(endpoint_urls)

        # Remove nodes that are no longer in the list
        for node in current_nodes - new_nodes:
            self.hash_ring.remove_node(node)

        # Add new nodes that are not already in the hash ring
        for node in new_nodes - current_nodes:
            self.hash_ring.add_node(node)

    def extract_session_id(self, request: Request, request_json: Dict) -> Optional[str]:
        """
        Extract the session id from the request headers or request body.
        """
        session_key = getattr(self, "session_key", None)
        if session_key is None:
            return None
        val = request.headers.get(session_key)
        return val if val is not None else request_json.get(session_key, None)

    @abc.abstractmethod
    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Route the request to the appropriate engine URL

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
        """
        raise NotImplementedError


class RoundRobinRouter(RoutingInterface):
    # TODO (ApostaC): when available engines in the endpoints changes, the
    # algorithm may not be "perfectly" round-robin.

    # Upper bound on cached endpoint-set entries to prevent unbounded memory
    # growth when endpoints change dynamically (add / remove / update).
    _MAX_CACHE_SIZE = 1024

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._next_index: dict[tuple[str, ...], int] = {}
        self._sorted_cache: dict[frozenset[str], tuple[str, ...]] = {}
        self._initialized = True

    def _endpoint_key(self, endpoints: List[EndpointInfo]) -> tuple[str, ...]:
        """Return a stable, sorted key for the endpoint set (cached after first sort)."""
        if not endpoints:
            raise ValueError("RoundRobinRouter requires at least one endpoint")

        urls = frozenset(e.url for e in endpoints)
        key = self._sorted_cache.get(urls)
        if key is None:
            if len(self._sorted_cache) >= self._MAX_CACHE_SIZE:
                self._sorted_cache.clear()
            key = tuple(sorted(urls))
            self._sorted_cache[urls] = key
        return key

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Route the request to the appropriate engine URL using a simple
        round-robin algorithm

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
        """
        endpoint_urls = self._endpoint_key(endpoints)
        idx = self._next_index.get(endpoint_urls, 0)
        if (
            len(self._next_index) >= self._MAX_CACHE_SIZE
            and endpoint_urls not in self._next_index
        ):
            self._next_index.clear()
        self._next_index[endpoint_urls] = idx + 1
        return endpoint_urls[idx % len(endpoint_urls)]


class SessionRouter(RoutingInterface):
    """
    Route the request to the appropriate engine URL based on the session key
    in the request headers
    """

    def __init__(self, session_key: str = None):
        if hasattr(self, "_initialized"):
            return
        if session_key is None:
            raise ValueError("SessionRouter must be initialized with a session_key")
        self.session_key = session_key
        self.hash_ring = HashRing()
        self._initialized = True

    async def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """
        Route the request to the appropriate engine URL by the 'session id' in
        the request headers or request body.
        If there is no session id in the request header or request body, it will pick a server
        with lowest qps

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
            request_json (Dict): The request body (needed for finding the session id)
        """
        session_id = self.extract_session_id(request, request_json)
        logger.debug(f"Got session id: {session_id}")

        # Update the hash ring with the current list of endpoints
        self._update_hash_ring(endpoints)

        if session_id is None:
            # Route based on QPS if no session ID is present
            url = self._qps_routing(endpoints, request_stats)
        else:
            # Use the hash ring to get the endpoint for the session ID
            url = self.hash_ring.get_node(session_id)

        return url


class KvawareRouter(RoutingInterface):
    """
    Route the request to the appropriate engine URL by where the KV cache
    of the longest prefix match is found.
    """

    def __init__(
        self,
        lmcache_controller_port: int,
        session_key: str,
        kv_aware_threshold: int = 2000,
        lmcache_health_check_interval: int = 5,
        lmcache_worker_timeout: int = 30,
        lmcache_controller_reply_port: Optional[int] = None,
        lmcache_controller_heartbeat_port: Optional[int] = None,
    ):
        self.lmcache_controller_port = lmcache_controller_port
        self.lmcache_controller_reply_port = lmcache_controller_reply_port
        self.lmcache_controller_heartbeat_port = lmcache_controller_heartbeat_port
        logger.info(
            f"Initializing KvawareRouter with port: {self.lmcache_controller_port}, "
            f"reply port: {self.lmcache_controller_reply_port}, "
            f"heartbeat port: {self.lmcache_controller_heartbeat_port}"
        )
        controller_urls = {
            "pull": f"0.0.0.0:{self.lmcache_controller_port}",
            "reply": (
                f"0.0.0.0:{self.lmcache_controller_reply_port}"
                if self.lmcache_controller_reply_port is not None
                else None
            ),
        }
        if self.lmcache_controller_heartbeat_port is not None:
            controller_urls["heartbeat"] = (
                f"0.0.0.0:{self.lmcache_controller_heartbeat_port}"
            )
        self.kv_manager = controller_manager.LMCacheControllerManager(
            controller_urls,
            health_check_interval=lmcache_health_check_interval,
            lmcache_worker_timeout=lmcache_worker_timeout,
        )
        self.req_id = 0
        self.instance_id_to_ip = {}
        self.session_key = session_key
        self.hash_ring = HashRing()
        self.tokenizer = None
        self.threshold = kv_aware_threshold

    def start_kv_manager(self):
        """
        Start the kv manager
        """
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.lmcache_cluster_monitor_task = asyncio.run_coroutine_threadsafe(
            self.kv_manager.start_all(), self.loop
        )

    def query_manager(self, msg) -> str:
        """
        Get the instance id for the given message
        """
        instance_id = self.kv_manager.handle_orchestration_message(msg)
        return instance_id

    def close(self):
        """Gracefully shutdown the lmcache cluster monitor task."""
        if (
            hasattr(self, "lmcache_cluster_monitor_task")
            and self.lmcache_cluster_monitor_task
        ):
            logger.info("Shutting down lmcache cluster monitor task")
            self.lmcache_cluster_monitor_task.cancel()
            try:
                self.lmcache_cluster_monitor_task.result()
            except concurrent.futures.CancelledError:
                pass
            self.lmcache_cluster_monitor_task = None

    async def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """
        Route the request to the appropriate engine URL by where the KV cache
        of the longest prefix match is found.
        If there is no session id in the request header, it will pick a server
        with round robin.

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
               the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
               indicating the request-level performance of each engine
            request (Request): The incoming request
            request_json (Dict): The request body (needed for finding the
            longest prefix match)
        """
        token_ids = None
        # Local-first tokenization, fall back to remote "/tokenize" API on failure
        # TODO (Yuhan): Handle chat completions
        try:
            if self.tokenizer is None:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    endpoints[0].model_names[0]
                )
            token_ids = self.tokenizer.encode(request_json.get("prompt", ""))
        except Exception:
            # Remote /tokenize fallback (let errors bubble up to keep behavior simple)
            remote_url = endpoints[0].url + "/tokenize"
            headers = {"Content-Type": "application/json"}
            data = {
                "model": endpoints[0].model_names[0],
                "prompt": request_json.get("prompt", ""),
            }
            body = requests.post(
                remote_url, headers=headers, json=data, timeout=10
            ).json()
            token_ids = body["tokens"]

        event_id = "Lookup" + str(uuid.uuid4())
        msg = LookupMsg(tokens=token_ids, event_id=event_id)
        instance_id = await self.query_manager(msg)
        matched_tokens = math.inf
        logger.debug(f"Lookup return message: {instance_id}")
        if len(list(instance_id.layout_info.keys())) > 0:
            matched_instance_id = list(instance_id.layout_info.keys())[
                0
            ]  # Get the first key
            matched_tokens = instance_id.layout_info[matched_instance_id][1]

        if (
            instance_id is None
            or len(instance_id.layout_info) == 0
            or matched_tokens < max(len(token_ids) - self.threshold, 0)
        ):
            session_id = self.extract_session_id(request, request_json)
            logger.debug(f"Fallback to using session id: {session_id}")
            # Update the hash ring with the current list of endpoints
            self._update_hash_ring(endpoints)
            if session_id is None:
                # Route based on QPS if no session ID is present
                url = self._qps_routing(endpoints, request_stats)
            else:
                # Use the hash ring to get the endpoint for the session ID
                url = self.hash_ring.get_node(session_id)
            return url
        else:
            queried_instance_ids = [info for info in instance_id.layout_info]
            if queried_instance_ids[0] not in self.instance_id_to_ip:
                for endpoint in endpoints:
                    event_id = "QueryInst" + str(uuid.uuid4())
                    query_ip = endpoint.url.split(f":{endpoint.url.split(':')[-1]}")[
                        0
                    ].split("//")[1]
                    query_message = QueryInstMsg(
                        ip=query_ip,
                        event_id=event_id,
                    )
                    endpoint_instance_id = await self.query_manager(query_message)
                    logger.debug(
                        f"Query ip: {query_ip}, return instance id: {endpoint_instance_id}"
                    )
                    self.instance_id_to_ip[endpoint_instance_id.instance_id] = (
                        endpoint.url
                    )
                logger.info(f"Instance id to ip mapping: {self.instance_id_to_ip}")
            logger.info(
                f"Routing request to {queried_instance_ids[0]} found by kvaware router"
            )
            return self.instance_id_to_ip[queried_instance_ids[0]]


class LoadAwareRouter(KvawareRouter):
    """KV-cache-aware placement that also weighs live engine load.

    `kvaware` maximizes cache-hit benefit alone: it takes the first instance
    reported in `layout_info` and sends the request there however busy that
    instance is. Under a workload with popular shared prefixes this
    concentrates load: every request for a hot prefix lands on the one engine
    holding it, which queues while its peers idle.

    `loadaware` scores **every** endpoint

        score(i) = matched_tokens(i) / prompt_tokens - beta * relative_load(i)

        relative_load(i) = (load(i) - mean_load) / max(1, mean_load)

    and routes to the argmax, so a warm-but-saturated instance can lose to a
    cold-but-idle one. It subclasses `KvawareRouter` and overrides only the
    selection step, so `kvaware` behaviour is unchanged.

    Design notes:

    1. **Benefit is normalized** to the fraction of the prompt already cached
       ([0, 1]) rather than a raw token count, so one beta means the same
       policy for a 500-token and a 4000-token prompt.
    2. **Load is normalized against the fleet's own mean**, which is what lets
       a single beta default ship: an absolute in-flight count has no bounded
       scale (it depends on request rate, prompt length and GPU), so the same
       beta would be a different policy on every deployment. The denominator
       is clamped at 1 so an essentially idle fleet reports no imbalance to
       act on.
    3. **Every endpoint is scored**, not only the holders in `layout_info`. An
       endpoint absent from `layout_info` scores benefit 0 - that is what
       makes "cold but idle beats warm but loaded" expressible at all.
    4. **`kv_aware_threshold` is not applied.** `kvaware` needs that band
       because it cannot weigh a small match against anything; the argmax can
       (a small match simply loses to load). The parameter is still accepted
       and forwarded for interface compatibility.

    When the controller reports no holder at all, placement falls back to the
    upstream session-hash / QPS route, exactly like `kvaware`.
    """

    def __init__(
        self,
        lmcache_controller_port: int,
        session_key: str,
        kv_aware_threshold: int = 2000,
        lmcache_health_check_interval: int = 5,
        lmcache_worker_timeout: int = 30,
        lmcache_controller_reply_port: Optional[int] = None,
        lmcache_controller_heartbeat_port: Optional[int] = None,
        loadaware_beta: Optional[float] = None,
    ):
        super().__init__(
            lmcache_controller_port,
            session_key,
            kv_aware_threshold if kv_aware_threshold is not None else 2000,
            lmcache_health_check_interval=lmcache_health_check_interval,
            lmcache_worker_timeout=lmcache_worker_timeout,
            lmcache_controller_reply_port=lmcache_controller_reply_port,
            lmcache_controller_heartbeat_port=lmcache_controller_heartbeat_port,
        )
        #: Weight on the load penalty, in units of "full cache hits per 100%
        #: above fleet-average load".
        self.beta = _loadaware_beta(loadaware_beta)
        logger.info(f"Initialized LoadAwareRouter with beta={self.beta}")

    @staticmethod
    def load_penalty(request_stats: Dict[str, RequestStats], url: str) -> int:
        """In-flight requests on `url` - prefilling plus decoding.

        `request_stats` is the fresh, event-driven stats source (the scraped
        `engine_stats` lags by `--engine-stats-interval`). A URL missing from
        it has served no requests yet, which is load 0 - the same reading
        `_qps_routing` gives an unseen endpoint.
        """
        stats = request_stats.get(url) if request_stats else None
        if stats is None:
            return 0
        return stats.in_prefill_requests + stats.in_decoding_requests

    @classmethod
    def relative_loads(
        cls, request_stats: Dict[str, RequestStats], endpoints: List[EndpointInfo]
    ) -> Dict[str, float]:
        """Each endpoint's load as a signed fraction of the fleet mean.

        `(load - mean) / max(1, mean)`: 0.0 is "average", +1.0 is "twice the
        fleet average" and -1.0 is "idle while the fleet is busy". The mean is
        recomputed per request from the same live `request_stats` the raw
        counts come from, so beta is self-calibrating.

        Clamping the denominator at 1 keeps a near-idle fleet quiet: without
        it a mean of 0.1 turns one in-flight request into a relative load of
        9.0, and the policy would thrash on noise at exactly the load level
        where there is nothing worth balancing.
        """
        loads = {
            endpoint.url: cls.load_penalty(request_stats, endpoint.url)
            for endpoint in endpoints
        }
        if not loads:
            return {}
        mean = sum(loads.values()) / len(loads)
        return {url: (load - mean) / max(1.0, mean) for url, load in loads.items()}

    def score_endpoint(
        self, matched_tokens: int, prompt_tokens: int, relative_load: float
    ) -> float:
        """`cache_hit_benefit - beta * relative_load` for one endpoint.

        Both terms are dimensionless: benefit is a fraction of *this prompt*,
        relative_load a fraction of *this fleet's* mean, so beta is a pure
        exchange rate between the two and carries no unit from the deployment.

        `matched_tokens` can come back larger than `prompt_tokens` when the
        match is rounded up to the token database's chunk boundary; the
        `min()` guard keeps benefit from exceeding 1.0 and outranking a
        genuine full hit.
        """
        benefit = min(matched_tokens, prompt_tokens) / max(prompt_tokens, 1)
        return benefit - self.beta * relative_load

    def matched_tokens_by_url(self, layout_info: Dict) -> Dict[str, int]:
        """Re-key the controller's answer from instance_id to engine URL.

        One URL can carry two instance_ids: a restarted engine registers under
        a fresh id while the dead one lingers both in this bridge and in the
        controller's `kv_pool`, so `lookup()` can still name the dead id as a
        holder. Only the **live** id may be credited: the restarted engine came
        back with an empty cache, so the dead id's match is phantom. Inverting
        the bridge resolves it - dicts preserve insertion order and
        `refresh_instance_map` appends ids as it learns them, so the last id
        written for a URL is the live one.
        """
        url_to_instance = {url: iid for iid, url in self.instance_id_to_ip.items()}
        matched = {}
        for url, instance_id in url_to_instance.items():
            info = layout_info.get(instance_id)
            if info is not None:
                matched[url] = info[1]
        return matched

    def select_url(
        self,
        endpoints: List[EndpointInfo],
        request_stats: Dict[str, RequestStats],
        layout_info: Dict,
        prompt_tokens: int,
    ) -> Optional[str]:
        """The placement decision. Pure: no I/O, no awaits.

        `layout_info` is keyed by instance_id and `request_stats` by engine
        URL; `self.instance_id_to_ip` bridges them, so it must be populated
        for every endpoint before this runs (`refresh_instance_map`).

        Ties break by lexicographic URL so a run is reproducible; returns None
        if there is nothing to route to, which the caller turns into the
        upstream fallback.
        """
        matched_by_url = self.matched_tokens_by_url(layout_info)
        relative = self.relative_loads(request_stats, endpoints)
        best_url = None
        best_score = -math.inf
        for info in sorted(endpoints, key=lambda e: e.url):
            matched_tokens = matched_by_url.get(info.url, 0)
            relative_load = relative.get(info.url, 0.0)
            score = self.score_endpoint(matched_tokens, prompt_tokens, relative_load)
            logger.debug(
                f"loadaware score {info.url}: "
                f"matched={matched_tokens}/{prompt_tokens} "
                f"rel_load={relative_load:+.3f} score={score:.4f}"
            )
            if score > best_score:
                best_score = score
                best_url = info.url
        return best_url

    def instance_map_is_stale(
        self, endpoints: List[EndpointInfo], layout_info: Dict
    ) -> bool:
        """Does the instance_id -> URL bridge still cover what we must score?

        Two ways it goes stale, and a count of entries catches neither,
        because the bridge only ever grows:

        - an endpoint we cannot score: some URL is not a value in the map, so
          its cache credit would read as 0 whatever it actually holds;
        - an unknown holder: `layout_info` names an instance_id the bridge has
          never seen - what an engine restart looks like, since the new
          process registers under a fresh id while the old one lingers here.

        Miss the second and placement silently degenerates to least-loaded
        for the life of the router, with nothing in the logs to say so.
        """
        mapped_urls = set(self.instance_id_to_ip.values())
        if any(endpoint.url not in mapped_urls for endpoint in endpoints):
            return True
        return any(
            instance_id not in self.instance_id_to_ip for instance_id in layout_info
        )

    async def refresh_instance_map(
        self, endpoints: List[EndpointInfo], layout_info: Dict
    ) -> None:
        """Populate instance_id -> URL for every endpoint, on demand.

        `KvawareRouter` builds this lazily and only far enough to translate
        the one instance it already picked; scoring needs the whole bridge.
        Each rebuild costs one awaited round-trip per endpoint to the
        controller (#1016: this path blocks the event loop), so it must stay a
        once-per-fleet-change cost, not a per-request one - hence the
        `instance_map_is_stale` gate rather than an unconditional refresh.
        """
        if not self.instance_map_is_stale(endpoints, layout_info):
            return

        async def query_endpoint(endpoint: EndpointInfo) -> None:
            event_id = "QueryInst" + str(uuid.uuid4())
            url = endpoint.url if "//" in endpoint.url else "//" + endpoint.url
            query_ip = urlparse(url).hostname or ""
            query_message = QueryInstMsg(ip=query_ip, event_id=event_id)
            endpoint_instance_id = await self.query_manager(query_message)
            logger.debug(
                f"Query ip: {query_ip}, return instance id: {endpoint_instance_id}"
            )
            self.instance_id_to_ip[endpoint_instance_id.instance_id] = endpoint.url

        await asyncio.gather(*(query_endpoint(e) for e in endpoints))
        logger.info(f"Instance id to ip mapping: {self.instance_id_to_ip}")

    async def tokenize_prompt(
        self, endpoints: List[EndpointInfo], request_json: Dict
    ) -> List[int]:
        """Local-first tokenization with the remote `/tokenize` fallback.

        The remote fallback is a blocking HTTP call, so it runs in an
        executor rather than on the event loop.
        """
        try:
            if self.tokenizer is None:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    endpoints[0].model_names[0]
                )
            return self.tokenizer.encode(request_json.get("prompt", ""))
        except Exception:
            remote_url = endpoints[0].url + "/tokenize"
            headers = {"Content-Type": "application/json"}
            data = {
                "model": endpoints[0].model_names[0],
                "prompt": request_json.get("prompt", ""),
            }
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(
                    remote_url, headers=headers, json=data, timeout=10
                ),
            )
            return response.json()["tokens"]

    def fallback_url(
        self,
        endpoints: List[EndpointInfo],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """Upstream's no-cache-info route: session hash if any, else lowest
        QPS."""
        session_id = self.extract_session_id(request, request_json)
        logger.debug(f"Fallback to using session id: {session_id}")
        self._update_hash_ring(endpoints)
        if session_id is None:
            return self._qps_routing(endpoints, request_stats)
        return self.hash_ring.get_node(session_id)

    async def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """
        Route the request to the engine with the best
        `cache_hit_benefit - beta * relative_load`.

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
               the 'physical' load of each engine. Unused: it is
               scrape-lagged, `request_stats` carries the live signal.
            request_stats (Dict[str, RequestStats]): The request stats
               indicating the request-level performance of each engine
            request (Request): The incoming request
            request_json (Dict): The request body (needed for the prefix
               match)

        Raises:
            HTTPException: 503 if no endpoints are available.
        """
        if not endpoints:
            raise HTTPException(
                status_code=503, detail="No backend endpoints available"
            )

        token_ids = await self.tokenize_prompt(endpoints, request_json)

        event_id = "Lookup" + str(uuid.uuid4())
        msg = LookupMsg(tokens=token_ids, event_id=event_id)
        lookup_ret = await self.query_manager(msg)
        logger.debug(f"Lookup return message: {lookup_ret}")
        layout_info = getattr(lookup_ret, "layout_info", None) or {}

        if not layout_info:
            # Nothing cached anywhere - no benefit term to weigh.
            return self.fallback_url(endpoints, request_stats, request, request_json)

        await self.refresh_instance_map(endpoints, layout_info)
        url = self.select_url(endpoints, request_stats, layout_info, len(token_ids))
        if url is None:
            return self.fallback_url(endpoints, request_stats, request, request_json)
        logger.info(f"Routing request to {url} found by loadaware router")
        return url


class PrefixAwareRouter(RoutingInterface):
    """
    Route the request to the appropriate engine URL by where the longest
    prefix match is found.

    In this class, we assume that there is no eviction of prefix cache.
    """

    def __init__(
        self,
        prefix_min_match_length: int = 0,
    ):
        if hasattr(self, "_initialized"):
            return
        from vllm_router.prefix.hashtrie import HashTrie

        self.hashtrie = HashTrie()
        self.prefix_min_match_length = prefix_min_match_length
        self._initialized = True

    async def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """
        Route the request to the appropriate engine URL by where the longest
        prefix match is found.

        In this routing logic, we do not consider the eviction of prefix cache.

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
               the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
               indicating the request-level performance of each engine
            request (Request): The incoming request
            request_json (Dict): The request body (needed for finding the
            longest prefix match)
        """

        # Handle chat completions
        if "messages" in request_json:
            # Get the last message from the messages array
            messages = request_json["messages"]
            if messages:
                # Concatenate all message content
                prompt_parts = []
                for message in messages:
                    content = message.get("content", "")
                    if isinstance(content, list):
                        # Handle multimodal messages
                        text_content = " ".join(
                            part.get("text", "")
                            for part in content
                            if part.get("type") == "text"
                        )
                        prompt_parts.append(text_content)
                    elif content is not None:
                        prompt_parts.append(content)
                prompt = "\n".join(prompt_parts)
            else:
                prompt = ""
        else:
            # Handle regular completions
            prompt = request_json["prompt"]

        available_endpoints = set(endpoint.url for endpoint in endpoints)
        match_length, matched_endpoint = await self.hashtrie.longest_prefix_match(
            prompt, available_endpoints
        )

        if match_length < self.prefix_min_match_length:
            # Fall back to QPS routing, but still record the prompt in the
            # trie. Without this, a router configured with
            # prefix_min_match_length > 0 starts with an empty trie, every
            # request matches below the threshold, nothing is ever inserted,
            # and prefix affinity never activates.
            selected_endpoint = self._qps_routing(endpoints, request_stats)
            if selected_endpoint is not None:
                await self.hashtrie.insert(prompt, selected_endpoint)
            return selected_endpoint

        selected_endpoint = random.choice(list(matched_endpoint))

        await self.hashtrie.insert(prompt, selected_endpoint)

        return selected_endpoint


class DisaggregatedPrefillRouter(RoutingInterface):
    """
    Route the request to the appropriate engine URL by handling prefill and decode operations sequentially.
    First request goes to prefill endpoint, then second request goes to decode endpoint.
    """

    def __init__(self, prefill_model_labels: List[str], decode_model_labels: List[str]):
        self.prefill_model_labels = prefill_model_labels
        self.decode_model_labels = decode_model_labels
        self.request_cache = {}  # Cache to store prefill results

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """
        Route the request to appropriate endpoints for prefill and decode operations.
        First request goes to prefill endpoint, then second request goes to decode endpoint.
        """
        # Find prefill and decode endpoints
        is_prefill = request_json.get("max_tokens", 0) == 1
        if is_prefill:
            logger.info("Prefill request")
        else:
            logger.info("Decode request")

        # Find endpoints with matching model labels
        prefiller_endpoints = [
            e for e in endpoints if e.model_label in self.prefill_model_labels
        ]
        decoder_endpoints = [
            e for e in endpoints if e.model_label in self.decode_model_labels
        ]
        if is_prefill:
            return prefiller_endpoints[0].url
        else:
            return decoder_endpoints[0].url


class DisaggregatedPrefillOrchestratedRouter(RoutingInterface):
    """
    Orchestrates disaggregated inference in a single request by chaining Prefill → Decode.

    Unlike DisaggregatedPrefillRouter (which requires 2 separate client requests),
    this router handles the entire flow internally:
    1. Receives request from client
    2. Forwards to Prefill endpoint with kv_transfer_params to enable disaggregated mode
    3. Gets prefill response with kv_transfer_params containing KV cache metadata
    4. Extracts kv_transfer_params, sets remote_host, and forwards to Decode
    5. Streams decode response back to client

    Load balancing: Uses round-robin across available prefill and decode pods.
    """

    def __init__(self, prefill_model_labels: List[str], decode_model_labels: List[str]):
        if hasattr(self, "_initialized"):
            return
        self.prefill_model_labels = prefill_model_labels or []
        self.decode_model_labels = decode_model_labels or []
        # Round-robin counters for load balancing across xPyD pods
        self.prefill_idx = 0
        self.decode_idx = 0
        self._initialized = True
        logger.info(
            f"Initialized DisaggregatedPrefillOrchestratedRouter with "
            f"prefill_labels={self.prefill_model_labels}, "
            f"decode_labels={self.decode_model_labels}"
        )

    def _find_endpoints(self, endpoints: List[EndpointInfo]):
        """Find prefill and decode endpoints based on model labels.

        Raises:
            HTTPException: 503 if prefill or decode endpoints are not available.
                - PREFILL_SERVICE_UNAVAILABLE: No prefill endpoints discovered
                - DECODE_SERVICE_UNAVAILABLE: No decode endpoints discovered
        """
        prefiller_endpoints = [
            e for e in endpoints if e.model_label in self.prefill_model_labels
        ]
        decoder_endpoints = [
            e for e in endpoints if e.model_label in self.decode_model_labels
        ]

        if not prefiller_endpoints:
            logger.warning(
                f"No prefill endpoints found with labels {self.prefill_model_labels}. "
                f"Available endpoints: {[(e.url, e.model_label) for e in endpoints]}"
            )
            raise HTTPException(
                status_code=503,
                detail="PREFILL_SERVICE_UNAVAILABLE: No prefill endpoints discovered",
            )
        if not decoder_endpoints:
            logger.warning(
                f"No decode endpoints found with labels {self.decode_model_labels}. "
                f"Available endpoints: {[(e.url, e.model_label) for e in endpoints]}"
            )
            raise HTTPException(
                status_code=503,
                detail="DECODE_SERVICE_UNAVAILABLE: No decode endpoints discovered",
            )

        return prefiller_endpoints, decoder_endpoints

    def select_prefill_endpoint(
        self, prefiller_endpoints: List[EndpointInfo]
    ) -> EndpointInfo:
        """Select prefill endpoint using round-robin load balancing."""
        if not prefiller_endpoints:
            raise ValueError("No prefill endpoints available")
        # Sort for consistency across requests
        sorted_endpoints = sorted(prefiller_endpoints, key=lambda e: e.url)
        selected = sorted_endpoints[self.prefill_idx % len(sorted_endpoints)]
        self.prefill_idx += 1
        return selected

    def select_decode_endpoint(
        self, decoder_endpoints: List[EndpointInfo]
    ) -> EndpointInfo:
        """Select decode endpoint using round-robin load balancing."""
        if not decoder_endpoints:
            raise ValueError("No decode endpoints available")
        # Sort for consistency across requests
        sorted_endpoints = sorted(decoder_endpoints, key=lambda e: e.url)
        selected = sorted_endpoints[self.decode_idx % len(sorted_endpoints)]
        self.decode_idx += 1
        return selected

    async def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict,
    ) -> str:
        """
        This method is called by the router framework but for orchestrated routing,
        we need to handle the full flow differently. This returns the prefill URL
        as a placeholder - the actual orchestration happens in route_orchestrated_disaggregated_request.
        """
        prefiller_endpoints, _ = self._find_endpoints(endpoints)
        # Return prefill URL - actual orchestration is done in request.py
        return prefiller_endpoints[0].url


# Instead of managing a global _global_router, we can define the initialization functions as:
def initialize_routing_logic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    if routing_logic == RoutingLogic.ROUND_ROBIN:
        logger.info("Initializing round-robin routing logic")
        router = RoundRobinRouter()
    elif routing_logic == RoutingLogic.SESSION_BASED:
        logger.info(f"Initializing session-based routing logic with kwargs: {kwargs}")
        router = SessionRouter(kwargs.get("session_key"))
    elif routing_logic == RoutingLogic.KVAWARE:
        logger.info("Initializing kvaware routing logic")
        router = KvawareRouter(
            lmcache_controller_port=kwargs.get("lmcache_controller_port"),
            session_key=kwargs.get("session_key"),
            kv_aware_threshold=kwargs.get("kv_aware_threshold"),
            lmcache_health_check_interval=kwargs.get("lmcache_health_check_interval"),
            lmcache_worker_timeout=kwargs.get("lmcache_worker_timeout"),
            lmcache_controller_reply_port=kwargs.get("lmcache_controller_reply_port"),
            lmcache_controller_heartbeat_port=kwargs.get(
                "lmcache_controller_heartbeat_port"
            ),
        )
        router.start_kv_manager()
    elif routing_logic == RoutingLogic.LOADAWARE:
        logger.info("Initializing loadaware routing logic")
        router = LoadAwareRouter(
            lmcache_controller_port=kwargs.get("lmcache_controller_port"),
            session_key=kwargs.get("session_key"),
            kv_aware_threshold=kwargs.get("kv_aware_threshold"),
            lmcache_health_check_interval=kwargs.get("lmcache_health_check_interval"),
            lmcache_worker_timeout=kwargs.get("lmcache_worker_timeout"),
            lmcache_controller_reply_port=kwargs.get("lmcache_controller_reply_port"),
            lmcache_controller_heartbeat_port=kwargs.get(
                "lmcache_controller_heartbeat_port"
            ),
            loadaware_beta=kwargs.get("loadaware_beta"),
        )
        router.start_kv_manager()
    elif routing_logic == RoutingLogic.PREFIXAWARE:
        logger.info("Initializing prefix-aware routing logic")
        router = PrefixAwareRouter(
            prefix_min_match_length=kwargs.get("prefix_min_match_length", 0),
        )
    elif routing_logic == RoutingLogic.DISAGGREGATED_PREFILL:
        logger.info("Initializing disaggregated prefill routing logic")
        router = DisaggregatedPrefillRouter(
            kwargs.get("prefill_model_labels"), kwargs.get("decode_model_labels")
        )
    elif routing_logic == RoutingLogic.DISAGGREGATED_PREFILL_ORCHESTRATED:
        logger.info("Initializing disaggregated prefill orchestrated routing logic")
        return DisaggregatedPrefillOrchestratedRouter(
            kwargs.get("prefill_model_labels"), kwargs.get("decode_model_labels")
        )
    else:
        raise ValueError(f"Invalid routing logic {routing_logic}")

    router.max_instance_failover_reroute_attempts = kwargs.get(
        "max_instance_failover_reroute_attempts", 0
    )
    return router


def reconfigure_routing_logic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    # Remove the existing routers from the singleton registry
    cleanup_routing_logic()
    return initialize_routing_logic(routing_logic, *args, **kwargs)


def get_routing_logic() -> RoutingInterface:
    # Look up in our singleton registry which router (if any) has been created.
    for cls in (
        SessionRouter,
        RoundRobinRouter,
        KvawareRouter,
        LoadAwareRouter,
        PrefixAwareRouter,
        DisaggregatedPrefillRouter,
        DisaggregatedPrefillOrchestratedRouter,
    ):
        if cls in SingletonABCMeta._instances:
            return cls()
    raise ValueError("The global router has not been initialized")


def cleanup_routing_logic():
    """Clean up all routing logic instances."""
    for cls in (
        SessionRouter,
        RoundRobinRouter,
        KvawareRouter,
        LoadAwareRouter,
        PrefixAwareRouter,
        DisaggregatedPrefillRouter,
        DisaggregatedPrefillOrchestratedRouter,
    ):
        if cls in SingletonABCMeta._instances:
            instance = cls()
            if hasattr(instance, "close"):
                instance.close()
            del SingletonABCMeta._instances[cls]
