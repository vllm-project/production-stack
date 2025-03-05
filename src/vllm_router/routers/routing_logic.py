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

from vllm_router.routers.affinity.factory import get_affinity
from vllm_router.routers.endpoint_filter.factory import get_endpoint_filter

logger = init_logger(__name__)


class RoutingInterface(metaclass=SingletonABCMeta):
    @abc.abstractmethod
    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict[str, Any],
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


class Router(RoutingInterface):

    def __init__(
        self, 
        **kwargs: Dict[str, Any],
    ):

        if hasattr(self, "_initialized"):
            return

        self.reconfigure(**kwargs)
        self.initialized = True

    def reconfigure(self, **kwargs: Dict[str, Any]):

        # Initialize the affinity module
        self.affinity = None
        if "affinity" not in kwargs:
            logger.warning("No affinity specified, using simple round-robin logic to select endpoints")
            self.affinity = get_affinity("round_robin", {})
        else:
            self.affinity = get_affinity(**kwargs["affinity"])

        # Initialize the endpoint filters
        self.endpoint_filters = []
        if "endpoint_filters" not in kwargs:
            logger.info("No endpoint filters specified.")
        else:
            for endpoint_filter_kwargs in kwargs["endpoint_filters"]:
                self.endpoint_filters.append(get_endpoint_filter(**endpoint_filter_kwargs))

        self._initialized = True


    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict[str, Any],
    ) -> str:

        self.affinity.update_endpoints_stats(endpoints, engine_stats, request_stats)

        endpoints = set(endpoint.url for endpoint in endpoints)
        assert endpoints, "No endpoints provided for the routing logic."

        for endpoint_filter in self.endpoint_filters:
            previous_endpoints = endpoints
            endpoints = endpoint_filter.get_filtered_endpoints(
                endpoints, 
                request_stats, 
                engine_stats
            )
            if not endpoints:
                logger.warning(f"Endpoint filter {endpoint_filter.name} "
                               f"removed all endpoints from "
                               f"{previous_endpoints}. Reverting to previous "
                               f"endpoints and skipping all remaining "
                               f"endpoint filters.")
                endpoints = previous_endpoints
                break

        selected_endpoint = self.affinity.get_high_affinity_endpoint(
            request, 
            request_json, 
            endpoints
        )

        self.affinity.on_request_routed(
            request, 
            request_json, 
            selected_endpoint
        )

        return selected_endpoint


_router = None

# Instead of managing a global _global_router, we can define the initialization functions as:
def initialize_routing_logic(
    **kwargs
) -> RoutingInterface:

    assert _router is None, "Routing logic already initialized"
    _router = Router(**kwargs)
    return _router


def reconfigure_routing_logic(
    **kwargs
) -> RoutingInterface:
    _router.reconfigure(**kwargs)
    return _router


def get_routing_logic() -> RoutingInterface:
    assert _router is not None, ("Routing logic not initialized. "
                                 "Please call initialize_routing_logic() first.")
    return _router
