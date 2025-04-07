import time
from typing import Dict, List, Optional, Tuple

from fastapi import Request

from vllm_router.log import init_logger
from vllm_router.routers.routing_logic import RoutingInterface
from vllm_router.service_discovery import EndpointInfo
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats
from vllm_router.utils import SingletonABCMeta

logger = init_logger(__name__)


class DisaggregatedQoERouter(RoutingInterface):
    """
    A QoE-centric router that explicitly disaggregates prefill and decoding phases
    using separate dedicated endpoints for each phase.

    This router maintains two categories of endpoints:
    1. Prefill endpoints: Optimized for initial token generation (TTFT)
    2. Decoding endpoints: Optimized for subsequent token generation (ITL)

    End-to-end QoE is measured from when a request first lands on a prefill endpoint
    until chat completion from a decoding endpoint.
    """

    def __init__(
        self,
        prefill_tag: str = "prefill",
        decoding_tag: str = "decoding",
        priority_header: str = "x-request-priority",
        expected_output_len_header: str = "x-expected-output-tokens",
        sla_header: str = "x-sla-target-ms",
    ):
        if hasattr(self, "_initialized"):
            return

        # Tags to identify different endpoint types
        self.prefill_tag = prefill_tag
        self.decoding_tag = decoding_tag

        # Request info headers
        self.priority_header = priority_header
        self.expected_output_len_header = expected_output_len_header
        self.sla_header = sla_header

        # Default weights for the QoE cost function
        self.prefill_weights = {
            "ttft": 0.5,  # Time to first token is critical for prefill
            "cache_hit": 0.3,  # GPU cache hit rate impacts prefill performance
            "queue_load": 0.2,  # Number of queued requests affects responsiveness
        }

        self.decoding_weights = {
            "itl": 0.6,  # Inter-token latency is critical for decoding
            "throughput": 0.3,  # Throughput affects overall completion speed
            "queue_load": 0.1,  # Fewer requests is less important for decoding
        }

        # Target values for good performance
        self.target_ttft = 300  # ms - target time to first token
        self.target_itl = 50  # ms - target inter-token latency
        self.optimal_throughput = 30  # tokens/second per request

        # Request tracking for cross-endpoint metrics
        self.request_tracking = {}  # request_id -> tracking data

        self._initialized = True

    def _filter_endpoints_by_tag(
        self, endpoints: List[EndpointInfo], tag: str
    ) -> List[EndpointInfo]:
        """
        Filter endpoints by a specific tag.

        Args:
            endpoints: List of all available endpoints
            tag: Tag to filter by ("prefill" or "decoding")

        Returns:
            List of endpoints with the specified tag
        """
        filtered = []
        for endpoint in endpoints:
            # Tags can be in metadata or in the URL/name
            is_tagged = False

            # Check in metadata
            if (
                hasattr(endpoint, "metadata")
                and endpoint.metadata
                and tag in endpoint.metadata.get("tags", [])
            ):
                is_tagged = True

            # Check in URL/name
            if tag in endpoint.url.lower() or (
                hasattr(endpoint, "name") and tag in endpoint.name.lower()
            ):
                is_tagged = True

            if is_tagged:
                filtered.append(endpoint)

        return filtered

    def _is_prefill_request(self, request: Request) -> bool:
        """
        Determine if the request is in the prefill phase (first request for a conversation).

        Args:
            request: The incoming request

        Returns:
            True if this is a prefill request, False if it's a decoding request
        """
        # Check if this appears to be the start of a conversation
        try:
            request_json = request.scope.get("json", {})

            # Check if this request has a previous message ID (indicating a decoding request)
            if "parent_id" in request_json or "previous_message_id" in request_json:
                return False

            # Check message structure
            messages = request_json.get("messages", [])
            if not messages:
                return True

            # If there are assistant messages, this is likely not the first request
            has_assistant = any(msg.get("role") == "assistant" for msg in messages)
            return not has_assistant

        except Exception as e:
            logger.debug(f"Error determining if request is prefill: {e}")
            # Default to treating as prefill if we can't determine
            return True

    def _extract_request_id(self, request: Request) -> str:
        """
        Extract a unique request ID from the request.

        Args:
            request: The incoming request

        Returns:
            A unique identifier for this request
        """
        # Try to get from headers first
        request_id = request.headers.get("x-request-id", None)

        # Fallback to request scope
        if not request_id:
            request_id = request.scope.get("request_id", None)

        # Final fallback to generated ID
        if not request_id:
            request_id = f"req_{int(time.time() * 1000)}_{id(request) % 10000}"

        return request_id

    def _extract_request_priority(self, request: Request) -> float:
        """
        Extract request priority from headers.

        Args:
            request: The incoming request

        Returns:
            Priority value (1=high, 2=medium, 3=low)
        """
        try:
            priority_str = request.headers.get(self.priority_header, "2")
            return float(priority_str)
        except (ValueError, TypeError):
            return 2.0  # Default to medium priority

    def _extract_expected_output_len(self, request: Request) -> int:
        """
        Extract expected output length from headers.

        Args:
            request: The incoming request

        Returns:
            Expected output length in tokens
        """
        try:
            length_str = request.headers.get(self.expected_output_len_header, "512")
            return int(length_str)
        except (ValueError, TypeError):
            return 512  # Default to medium output length

    def _calculate_prefill_score(
        self,
        url: str,
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> float:
        """
        Calculate a score for prefill performance of an endpoint.
        Lower score is better.

        Args:
            url: Endpoint URL
            engine_stats: Dictionary of engine stats
            request_stats: Dictionary of request stats

        Returns:
            Prefill performance score (0-1, lower is better)
        """
        if url not in request_stats:
            return 0.5  # Neutral score for unknown endpoints

        rs = request_stats[url]
        es = engine_stats.get(url, None)

        # TTFT score (normalized to target)
        ttft_factor = (
            min(1.0, rs.ttft * 1000 / self.target_ttft) if rs.ttft > 0 else 0.5
        )

        # GPU cache hit rate
        cache_factor = 0.0
        if es and es.gpu_prefix_cache_hit_rate is not None:
            cache_factor = (
                1.0 - es.gpu_prefix_cache_hit_rate
            )  # Higher hit rate = lower cost
        else:
            cache_factor = 0.5  # Neutral if not available

        # Queue load factor
        queue_factor = 0.0
        if es and es.num_queuing_requests is not None:
            queue_factor = min(1.0, es.num_queuing_requests / 10.0)
        else:
            queue_factor = 0.5  # Neutral if not available

        # Weighted sum for prefill score
        prefill_score = (
            self.prefill_weights["ttft"] * ttft_factor
            + self.prefill_weights["cache_hit"] * cache_factor
            + self.prefill_weights["queue_load"] * queue_factor
        )

        return prefill_score

    def _calculate_decoding_score(
        self,
        url: str,
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        expected_output_len: int,
    ) -> float:
        """
        Calculate a score for decoding performance of an endpoint.
        Lower score is better.

        Args:
            url: Endpoint URL
            engine_stats: Dictionary of engine stats
            request_stats: Dictionary of request stats
            expected_output_len: Expected output length in tokens

        Returns:
            Decoding performance score (0-1, lower is better)
        """
        if url not in request_stats:
            return 0.5  # Neutral score for unknown endpoints

        rs = request_stats[url]
        es = engine_stats.get(url, None)

        # Inter-token latency score
        itl_factor = (
            min(1.0, rs.avg_itl * 1000 / self.target_itl) if rs.avg_itl > 0 else 0.5
        )

        # Throughput score
        throughput_factor = 0.5  # Default neutral
        if hasattr(rs, "tokens_per_second") and rs.tokens_per_second > 0:
            throughput_factor = max(
                0, min(1.0, 1.0 - (rs.tokens_per_second / self.optimal_throughput))
            )
        elif rs.avg_itl > 0:
            # Estimate throughput from ITL if available
            est_throughput = (
                1 / rs.avg_itl if rs.avg_itl > 0 else self.optimal_throughput
            )
            throughput_factor = max(
                0, min(1.0, 1.0 - (est_throughput / self.optimal_throughput))
            )

        # Queue load factor
        queue_factor = 0.0
        if es and es.num_queuing_requests is not None:
            queue_factor = min(
                1.0, es.num_queuing_requests / 15.0
            )  # Decoding can handle more queued requests
        else:
            queue_factor = 0.5  # Neutral if not available

        # For very long outputs, throughput becomes more important
        weights = self.decoding_weights.copy()
        if expected_output_len > 1000:
            weights["throughput"] += 0.1
            weights["itl"] -= 0.1

        # Weighted sum for decoding score
        decoding_score = (
            weights["itl"] * itl_factor
            + weights["throughput"] * throughput_factor
            + weights["queue_load"] * queue_factor
        )

        return decoding_score

    def route_prefill_request(
        self,
        prefill_endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_id: str,
        priority: float,
    ) -> str:
        """
        Route a prefill-phase request to the appropriate prefill endpoint.

        Args:
            prefill_endpoints: List of prefill-optimized endpoints
            engine_stats: Dictionary of engine stats
            request_stats: Dictionary of request stats
            request: The incoming request
            request_id: Unique request identifier
            priority: Request priority

        Returns:
            URL of the selected endpoint
        """
        if not prefill_endpoints:
            logger.warning("No prefill endpoints available")
            raise ValueError("No prefill endpoints available")

        # Calculate prefill score for each endpoint
        endpoint_scores = {}
        for endpoint in prefill_endpoints:
            url = endpoint.url
            score = self._calculate_prefill_score(url, engine_stats, request_stats)

            # Apply priority factor - higher priority (lower value) reduces score
            priority_factor = (priority - 1) / 2.0  # Normalize to 0-1
            score = score * (1.0 + 0.2 * priority_factor)  # Up to 20% adjustment

            endpoint_scores[url] = score
            logger.debug(f"Prefill endpoint {url} has score: {score}")

        # Choose endpoint with lowest score
        if not endpoint_scores:
            return prefill_endpoints[0].url

        best_url = min(endpoint_scores.items(), key=lambda x: x[1])[0]

        # Track the prefill start time for this request
        self.request_tracking[request_id] = {
            "prefill_start_time": time.time(),
            "prefill_endpoint": best_url,
            "priority": priority,
        }

        logger.info(f"Routed prefill request {request_id} to endpoint {best_url}")
        return best_url

    def route_decoding_request(
        self,
        decoding_endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_id: str,
        priority: float,
        expected_output_len: int,
    ) -> str:
        """
        Route a decoding-phase request to the appropriate decoding endpoint.

        Args:
            decoding_endpoints: List of decoding-optimized endpoints
            engine_stats: Dictionary of engine stats
            request_stats: Dictionary of request stats
            request: The incoming request
            request_id: Unique request identifier
            priority: Request priority
            expected_output_len: Expected output length in tokens

        Returns:
            URL of the selected endpoint
        """
        if not decoding_endpoints:
            logger.warning("No decoding endpoints available")
            raise ValueError("No decoding endpoints available")

        # Calculate decoding score for each endpoint
        endpoint_scores = {}
        for endpoint in decoding_endpoints:
            url = endpoint.url
            score = self._calculate_decoding_score(
                url, engine_stats, request_stats, expected_output_len
            )

            # Apply priority factor - higher priority (lower value) reduces score
            priority_factor = (priority - 1) / 2.0  # Normalize to 0-1
            score = score * (1.0 + 0.2 * priority_factor)  # Up to 20% adjustment

            endpoint_scores[url] = score
            logger.debug(f"Decoding endpoint {url} has score: {score}")

        # Choose endpoint with lowest score
        if not endpoint_scores:
            return decoding_endpoints[0].url

        best_url = min(endpoint_scores.items(), key=lambda x: x[1])[0]

        # Update tracking info for this request
        if request_id in self.request_tracking:
            self.request_tracking[request_id]["decoding_start_time"] = time.time()
            self.request_tracking[request_id]["decoding_endpoint"] = best_url

            # Calculate and log prefill time if available
            prefill_time = (
                self.request_tracking[request_id]["decoding_start_time"]
                - self.request_tracking[request_id]["prefill_start_time"]
            )
            logger.info(
                f"Request {request_id} completed prefill phase in {prefill_time:.3f}s"
            )
        else:
            # This is a decoding request we haven't seen the prefill for
            self.request_tracking[request_id] = {
                "decoding_start_time": time.time(),
                "decoding_endpoint": best_url,
                "priority": priority,
            }

        logger.info(f"Routed decoding request {request_id} to endpoint {best_url}")
        return best_url

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Main entry point for request routing.
        Routes requests based on their phase (prefill or decoding) to dedicated endpoints.

        Args:
            endpoints: List of all available endpoints
            engine_stats: Dictionary of engine stats
            request_stats: Dictionary of request stats
            request: The incoming request

        Returns:
            URL of the selected endpoint
        """
        if not endpoints:
            logger.warning("No endpoints available")
            raise ValueError("No endpoints available")

        # Extract request metadata
        is_prefill = self._is_prefill_request(request)
        request_id = self._extract_request_id(request)
        priority = self._extract_request_priority(request)
        expected_output_len = self._extract_expected_output_len(request)

        # Log the request characteristics
        logger.debug(
            f"Routing request: id={request_id}, prefill={is_prefill}, priority={priority}, expected_length={expected_output_len}"
        )

        # Filter endpoints by type
        if is_prefill:
            prefill_endpoints = self._filter_endpoints_by_tag(
                endpoints, self.prefill_tag
            )
            if not prefill_endpoints:
                logger.warning(
                    f"No endpoints with tag '{self.prefill_tag}' found, falling back to all endpoints"
                )
                prefill_endpoints = endpoints
            return self.route_prefill_request(
                prefill_endpoints,
                engine_stats,
                request_stats,
                request,
                request_id,
                priority,
            )
        else:
            decoding_endpoints = self._filter_endpoints_by_tag(
                endpoints, self.decoding_tag
            )
            if not decoding_endpoints:
                logger.warning(
                    f"No endpoints with tag '{self.decoding_tag}' found, falling back to all endpoints"
                )
                decoding_endpoints = endpoints
            return self.route_decoding_request(
                decoding_endpoints,
                engine_stats,
                request_stats,
                request,
                request_id,
                priority,
                expected_output_len,
            )

    def on_request_complete(self, request_id: str, success: bool = True):
        """
        Called when a request is completed.
        Updates tracking information and calculates end-to-end QoE metrics.

        Args:
            request_id: Unique request identifier
            success: Whether the request completed successfully
        """
        if request_id not in self.request_tracking:
            return

        end_time = time.time()
        tracking_data = self.request_tracking[request_id]

        # Calculate end-to-end latency if we have both prefill and decoding data
        if (
            "prefill_start_time" in tracking_data
            and "decoding_start_time" in tracking_data
        ):
            prefill_time = (
                tracking_data["decoding_start_time"]
                - tracking_data["prefill_start_time"]
            )
            total_time = end_time - tracking_data["prefill_start_time"]
            decoding_time = end_time - tracking_data["decoding_start_time"]

            logger.info(
                f"Request {request_id} completed with total time {total_time:.3f}s "
                f"(prefill: {prefill_time:.3f}s, decoding: {decoding_time:.3f}s)"
            )

            # Log SLA compliance if applicable
            if "priority" in tracking_data:
                priority = tracking_data["priority"]
                sla_threshold = 2.0  # Default SLA in seconds
                if priority == 1:
                    sla_threshold = 1.0  # Higher priority = stricter SLA
                elif priority == 3:
                    sla_threshold = 3.0  # Lower priority = relaxed SLA

                logger.info(
                    f"Request {request_id} SLA compliance: {total_time <= sla_threshold} "
                    f"(actual: {total_time:.3f}s, threshold: {sla_threshold:.3f}s)"
                )

        # Clean up tracking data
        if success:
            del self.request_tracking[request_id]
        else:
            # Mark as failed but keep for diagnostics
            tracking_data["failed"] = True
            tracking_data["failure_time"] = end_time
