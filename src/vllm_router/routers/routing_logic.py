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
import enum
from typing import Dict, List

from fastapi import Request
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
    QOE_CENTRIC = "qoe_centric"


class RoutingInterface(metaclass=SingletonABCMeta):
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
    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self.req_id = 0
        self._initialized = True

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
        len_engines = len(endpoints)
        chosen = sorted(endpoints, key=lambda e: e.url)[self.req_id % len_engines]
        self.req_id += 1
        return chosen.url


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

    def _qps_routing(
        self, endpoints: List[EndpointInfo], request_stats: Dict[str, RequestStats]
    ) -> str:
        """
        Route the request to the appropriate engine URL based on the QPS of
        each engine

        Args:
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

    def _update_hash_ring(self, endpoints: List[EndpointInfo]):
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

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Route the request to the appropriate engine URL by the 'session id' in
        the request headers.
        If there is no session id in the request header, it will pick a server
        with lowest qps

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
        """
        session_id = request.headers.get(self.session_key, None)
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


class QoECentricRouter(RoutingInterface):
    """
    Route requests using a QoE-centric approach that differentiates between
    prefill and decoding phases of LLM inference to optimize user experience.
    """

    def __init__(
        self,
        priority_header: str = "x-request-priority",
        expected_output_len_header: str = "x-expected-output-tokens",
        sla_header: str = "x-sla-target-ms",
    ):
        if hasattr(self, "_initialized"):
            return

        # Request info headers
        self.priority_header = priority_header
        self.expected_output_len_header = expected_output_len_header
        self.sla_header = sla_header

        # Default weights for the QoE cost function
        self.alpha = 0.3  # Resource utilization weight
        self.beta = 0.4  # Performance metrics weight
        self.gamma = 0.2  # Reliability metrics weight
        self.delta = 0.1  # Priority-based weight

        # Target values for good performance
        self.target_ttft = 300  # ms - target time to first token
        self.target_itl = 50  # ms - target inter-token latency
        self.optimal_throughput = 30  # tokens/second per request

        # Adaptation thresholds
        self.prefill_load_threshold = 5  # Number of active prefill requests
        self.decoding_load_threshold = 10  # Number of active decoding requests

        self._initialized = True

    def _calculate_prefill_score(
        self,
        url: str,
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> float:
        """
        Calculate a score for prefill performance of an endpoint.
        Lower score is better.
        """
        if url not in request_stats:
            return 0.0  # No data, assume good performance

        rs = request_stats[url]
        es = engine_stats.get(url, None)

        # Prefill prefers endpoints with good TTFT (time to first token)
        ttft_factor = (
            min(1.0, rs.ttft * 1000 / self.target_ttft) if rs.ttft > 0 else 0.5
        )

        # Prefill phase benefits from GPU cache hits
        cache_factor = 0.0
        if es:
            cache_factor = 1.0 - (
                es.gpu_prefix_cache_hit_rate
                if es.gpu_prefix_cache_hit_rate is not None
                else 0.0
            )

        # Prefill phase prefers fewer active prefill requests
        load_factor = (
            min(1.0, rs.in_prefill_requests / self.prefill_load_threshold)
            if self.prefill_load_threshold > 0
            else 0.0
        )

        # Weighted sum for prefill score (lower is better)
        prefill_score = 0.5 * ttft_factor + 0.3 * cache_factor + 0.2 * load_factor

        return prefill_score

    def _calculate_decoding_score(
        self,
        url: str,
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> float:
        """
        Calculate a score for decoding performance of an endpoint.
        Lower score is better.
        """
        if url not in request_stats:
            return 0.0  # No data, assume good performance

        rs = request_stats[url]

        # Decoding prefers endpoints with good inter-token latency
        itl_factor = (
            min(1.0, rs.avg_itl * 1000 / self.target_itl) if rs.avg_itl > 0 else 0.5
        )

        # Decoding phase prefers balanced number of active decoding requests
        # to maximize throughput while avoiding overwhelming a single endpoint
        load_factor = (
            min(1.0, rs.in_decoding_requests / self.decoding_load_threshold)
            if self.decoding_load_threshold > 0
            else 0.0
        )

        # Weighted sum for decoding score (lower is better)
        decoding_score = 0.7 * itl_factor + 0.3 * load_factor

        return decoding_score

    def _is_prefill_request(self, request: Request) -> bool:
        """
        Determine if the request is in the prefill phase (first request for a conversation).
        This is a simplification - in a real system you would determine this from the request context.
        """
        # Check if this appears to be the start of a conversation
        try:
            request_json = request.scope.get("json", {})
            messages = request_json.get("messages", [])
            # If there are no messages or only system/user messages without assistant messages,
            # this is likely a prefill request
            if not messages:
                return True

            has_assistant = any(msg.get("role") == "assistant" for msg in messages)
            return not has_assistant
        except Exception as e:
            logger.debug(f"Error determining if request is prefill: {e}")
            # Default to treating as prefill if we can't determine
            return True

    def _extract_request_priority(self, request: Request) -> float:
        """Extract request priority from headers or default to medium priority"""
        try:
            priority_str = request.headers.get(self.priority_header, "2")
            return float(priority_str)
        except (ValueError, TypeError):
            return 2.0  # Default to medium priority (1=high, 2=medium, 3=low)

    def _extract_expected_output_len(self, request: Request) -> int:
        """Extract expected output length from headers or default to medium length"""
        try:
            length_str = request.headers.get(self.expected_output_len_header, "512")
            return int(length_str)
        except (ValueError, TypeError):
            return 512  # Default to medium output length

    def _calculate_qoe_cost(
        self,
        url: str,
        is_prefill: bool,
        priority: float,
        expected_length: int,
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> float:
        """
        Calculate the QoE-centric cost function for routing decisions.
        Lower cost is better.
        """
        # Resource utilization term
        resource_cost = 0.0
        if url in engine_stats:
            es = engine_stats[url]
            gpu_usage = (
                es.gpu_cache_usage_perc if es.gpu_cache_usage_perc is not None else 0.5
            )
            queue_load = (
                min(1.0, (es.num_queuing_requests / 10.0))
                if es.num_queuing_requests is not None
                else 0.0
            )
            resource_cost = 0.6 * gpu_usage + 0.4 * queue_load

        # Performance term - depends on whether this is prefill or decoding
        if is_prefill:
            performance_cost = self._calculate_prefill_score(
                url, engine_stats, request_stats
            )
        else:
            performance_cost = self._calculate_decoding_score(
                url, engine_stats, request_stats
            )

        # Reliability cost - simplified
        reliability_cost = 0.0
        if url in request_stats:
            # For now, just use a simple uptime score as a proxy for reliability
            rs = request_stats[url]
            uptime_hours = rs.uptime / 3600.0 if rs.uptime > 0 else 0
            reliability_cost = max(
                0, min(1.0, 1.0 - (uptime_hours / 24.0))
            )  # Higher uptime means lower cost

        # Priority cost - higher priority (lower value) reduces the cost
        priority_cost = (
            priority - 1
        ) / 2.0  # Normalize priority to 0-1 range (1=high -> 0, 3=low -> 1)

        # Long output requests are better for decoding-optimized endpoints
        if not is_prefill and expected_length > 1000:
            performance_cost *= 0.8  # Reduce cost for long output during decoding

        # Calculate final weighted cost
        qoe_cost = (
            self.alpha * resource_cost
            + self.beta * performance_cost
            + self.gamma * reliability_cost
            + self.delta * priority_cost
        )

        return qoe_cost

    def _adapt_parameters(self, request_stats: Dict[str, RequestStats]):
        """Dynamically adapt weights based on system conditions"""
        # Check if we have high prefill load across endpoints
        total_prefill = sum(rs.in_prefill_requests for rs in request_stats.values())
        total_decoding = sum(rs.in_decoding_requests for rs in request_stats.values())

        if total_prefill > self.prefill_load_threshold * len(request_stats):
            # Increase prefill importance when many prefill requests are waiting
            self.beta += 0.05
            self.alpha -= 0.03
            self.gamma -= 0.02
        elif total_decoding > self.decoding_load_threshold * len(request_stats):
            # Balance more toward throughput when many decoding requests are active
            self.alpha += 0.05
            self.beta -= 0.03
            self.gamma -= 0.02

        # Renormalize weights to sum to 1
        total = self.alpha + self.beta + self.gamma + self.delta
        self.alpha /= total
        self.beta /= total
        self.gamma /= total
        self.delta /= total

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Route the request using QoE-centric approach that separates
        prefill and decoding phases of LLM inference.

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
        """
        if not endpoints:
            logger.warning("No endpoints available for routing")
            raise ValueError("No endpoints available")

        # Extract request characteristics
        is_prefill = self._is_prefill_request(request)
        priority = self._extract_request_priority(request)
        expected_length = self._extract_expected_output_len(request)

        # Log the request characteristics
        logger.debug(
            f"Routing request: prefill={is_prefill}, priority={priority}, expected_length={expected_length}"
        )

        # Periodically adapt parameters based on system state
        self._adapt_parameters(request_stats)

        # Calculate QoE cost for each endpoint
        endpoint_costs = {}
        for endpoint in endpoints:
            url = endpoint.url
            cost = self._calculate_qoe_cost(
                url, is_prefill, priority, expected_length, engine_stats, request_stats
            )
            endpoint_costs[url] = cost
            logger.debug(f"Endpoint {url} has QoE cost: {cost}")

        # Choose endpoint with lowest cost
        if not endpoint_costs:
            # If we couldn't calculate costs, fall back to a simple method
            return endpoints[0].url

        best_url = min(endpoint_costs.items(), key=lambda x: x[1])[0]
        logger.info(
            f"QoE-centric routing chose endpoint {best_url} for {'prefill' if is_prefill else 'decoding'} request"
        )

        return best_url


# Instead of managing a global _global_router, we can define the initialization functions as:
def initialize_routing_logic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    if routing_logic == RoutingLogic.ROUND_ROBIN:
        logger.info("Initializing round-robin routing logic")
        return RoundRobinRouter()
    elif routing_logic == RoutingLogic.SESSION_BASED:
        logger.info(f"Initializing session-based routing logic with kwargs: {kwargs}")
        return SessionRouter(kwargs.get("session_key"))
    elif routing_logic == RoutingLogic.QOE_CENTRIC:
        logger.info(f"Initializing QoE-centric routing logic with kwargs: {kwargs}")
        return QoECentricRouter(
            priority_header=kwargs.get("priority_header", "x-request-priority"),
            expected_output_len_header=kwargs.get(
                "expected_output_len_header", "x-expected-output-tokens"
            ),
            sla_header=kwargs.get("sla_header", "x-sla-target-ms"),
        )
    else:
        raise ValueError(f"Invalid routing logic {routing_logic}")


def reconfigure_routing_logic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    # Remove the existing routers from the singleton registry
    for cls in (SessionRouter, RoundRobinRouter, QoECentricRouter):
        if cls in SingletonABCMeta._instances:
            del SingletonABCMeta._instances[cls]
    return initialize_routing_logic(routing_logic, *args, **kwargs)


def get_routing_logic() -> RoutingInterface:
    # Look up in our singleton registry which router (if any) has been created.
    for cls in (SessionRouter, RoundRobinRouter, QoECentricRouter):
        if cls in SingletonABCMeta._instances:
            return cls()
    raise ValueError("The global router has not been initialized")
