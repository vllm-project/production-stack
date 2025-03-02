import abc
import enum
import hashlib
from typing import Dict, List, Optional, Tuple

from fastapi import Request
from uhashring import HashRing

from vllm_router.engine_stats import EngineStats
from vllm_router.log import init_logger
from vllm_router.request_stats import RequestStats
from vllm_router.service_discovery import EndpointInfo
from vllm_router.utils import SingletonABCMeta

logger = init_logger(__name__)


class RoutingLogic(str, enum.Enum):
    ROUND_ROBIN = "roundrobin"
    SESSION_BASED = "session"
    WEIGHTED = "weighted"


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


class WeightedRouter(RoutingInterface):
    """
    Route requests using Smooth Weighted Round Robin algorithm.
    This provides proportional distribution of requests across endpoints based on their weights.
    """

    def __init__(self, weights: Dict[str, int] = None):
        if hasattr(self, "_initialized"):
            return
        if weights is None:
            raise ValueError("WeightedRouter must be initialized with weights")

        self.static_weights = weights  # The configured static weights
        self.current_weights = {}  # Dynamic weights used in the algorithm
        self.last_endpoints = set()  # Track endpoint changes
        self._initialized = True

    def _initialize_current_weights(self, endpoints: List[EndpointInfo]):
        """Initialize or reset current weights when endpoints change."""
        current_endpoints = {endpoint.url for endpoint in endpoints}

        # If endpoints have changed, reset the weights
        if current_endpoints != self.last_endpoints:
            self.current_weights = {}
            for endpoint in endpoints:
                # Use configured weight or default to 1
                self.current_weights[endpoint.url] = self.static_weights.get(
                    endpoint.url, 1
                )
            self.last_endpoints = current_endpoints

    def _get_total_weight(self) -> int:
        """Calculate the total weight of all active endpoints."""
        return sum(self.static_weights.get(url, 1) for url in self.last_endpoints)

    def _select_endpoint(self) -> str:
        """Select the next endpoint using SWRR algorithm."""
        max_weight = float("-inf")
        selected_url = None

        # Select the server with the highest current weight
        for url, weight in self.current_weights.items():
            if weight > max_weight:
                max_weight = weight
                selected_url = url

        if selected_url is None:
            raise RuntimeError("No endpoints available for selection")

        # Decrease the current weight of the selected server by total weight
        self.current_weights[selected_url] -= self._get_total_weight()

        # Increase all current weights by their static weights
        for url in self.current_weights:
            self.current_weights[url] += self.static_weights.get(url, 1)

        return selected_url

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Route the request using Smooth Weighted Round Robin algorithm.

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
        """
        self._initialize_current_weights(endpoints)
        return self._select_endpoint()


# Instead of managing a global _global_router, we can define the initialization functions as:
def InitializeRoutingLogic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    if routing_logic == RoutingLogic.ROUND_ROBIN:
        logger.info("Initializing round-robin routing logic")
        return RoundRobinRouter()
    elif routing_logic == RoutingLogic.SESSION_BASED:
        logger.info(f"Initializing session-based routing logic with kwargs: {kwargs}")
        return SessionRouter(kwargs.get("session_key"))
    elif routing_logic == RoutingLogic.WEIGHTED:
        logger.info(
            f"Initializing weighted routing logic with weights: {kwargs.get('weights')}"
        )
        return WeightedRouter(kwargs.get("weights"))
    else:
        raise ValueError(f"Invalid routing logic {routing_logic}")


def ReconfigureRoutingLogic(
    routing_logic: RoutingLogic, *args, **kwargs
) -> RoutingInterface:
    # Remove the existing routers from the singleton registry
    for cls in (SessionRouter, RoundRobinRouter, WeightedRouter):
        if cls in SingletonABCMeta._instances:
            del SingletonABCMeta._instances[cls]
    return InitializeRoutingLogic(routing_logic, *args, **kwargs)


def GetRoutingLogic() -> RoutingInterface:
    # Look up in our singleton registry which router (if any) has been created.
    for cls in (SessionRouter, RoundRobinRouter, WeightedRouter):
        if cls in SingletonABCMeta._instances:
            return cls()
    raise ValueError("The global router has not been initialized")
