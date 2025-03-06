import abc
import enum
import json
from typing import Any, Dict, List

from fastapi import Request
from uhashring import HashRing

from vllm_router.log import init_logger
from vllm_router.service_discovery import EndpointInfo
from vllm_router.services.routing_service.affinity.factory import get_affinity
from vllm_router.services.routing_service.endpoint_filter.factory import (
    get_endpoint_filter,
)
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats
from vllm_router.utils import SingletonABCMeta

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
        routing_logic: str,
        routing_logic_config: Dict[str, Any],
        endpoint_filters: List[str],
        endpoint_filters_configs: List[Dict[str, Any]],
    ):

        if hasattr(self, "_initialized"):
            return

        self.reconfigure(
            routing_logic=routing_logic,
            routing_logic_config=routing_logic_config,
            endpoint_filters=endpoint_filters,
            endpoint_filters_configs=endpoint_filters_configs,
        )
        self.initialized = True

    def reconfigure(
        self,
        routing_logic: str,
        routing_logic_config: str,
        endpoint_filters: List[str],
        endpoint_filters_configs: List[str],
    ):

        # Initialize the affinity module
        self.affinity = None

        routing_logic_config = json.loads(routing_logic_config)
        self.affinity = get_affinity(routing_logic, **routing_logic_config)

        # Initialize the endpoint filters
        self.endpoint_filters = []

        assert len(endpoint_filters) == len(endpoint_filters_configs), (
            "The number of items in endpoint filters and endpoint filter "
            "configs must be the same"
        )

        for endpoint_filter_name, endpoint_filter_config in zip(
            endpoint_filters, endpoint_filters_configs
        ):
            self.endpoint_filters.append(
                get_endpoint_filter(
                    endpoint_filter_name, **json.loads(endpoint_filter_config)
                )
            )

        self._initialized = True

    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
        request_json: Dict[str, Any],
    ) -> str:

        endpoints = set(endpoint.url for endpoint in endpoints)
        assert endpoints, "No endpoints provided for the routing logic."

        for endpoint_filter in self.endpoint_filters:
            previous_endpoints = endpoints
            endpoints = endpoint_filter.get_filtered_endpoints(
                endpoints, request_stats, engine_stats
            )
            if not endpoints:
                logger.warning(
                    f"Endpoint filter {endpoint_filter.name} "
                    f"removed all endpoints from "
                    f"{previous_endpoints}. Reverting to previous "
                    f"endpoints and skipping all remaining "
                    f"endpoint filters."
                )
                endpoints = previous_endpoints
                break

        # NOTE(Kuntai): Only update the endpoint stats for the candidate
        # endpoints instead of all endpoints.
        # Another design is to actually update the endpoint stats for all
        # endpoints. But I don't see that there is a strong reason to do so.
        self.affinity.update_endpoints_stats(endpoints, engine_stats, request_stats)

        selected_endpoint = self.affinity.get_high_affinity_endpoint(
            request, request_json, endpoints
        )

        self.affinity.on_request_routed(request, request_json, selected_endpoint)

        return selected_endpoint


_router = None


# Instead of managing a global _global_router, we can define the initialization functions as:
def initialize_routing_logic(
    routing_logic: str,
    session_key: str,
    routing_logic_config: str,
    endpoint_filters: List[str],
    endpoint_filters_configs: str,
) -> RoutingInterface:

    global _router
    assert _router is None, "Routing logic already initialized"
    if routing_logic == "session":
        routing_logic_config.update({"session_key": session_key})
    _router = Router(
        routing_logic=routing_logic,
        routing_logic_config=routing_logic_config,
        endpoint_filters=endpoint_filters,
        endpoint_filters_configs=endpoint_filters_configs,
    )
    return _router


def reconfigure_routing_logic(
    routing_logic: str,
    session_key: str,
    routing_logic_config: str,
    endpoint_filters: List[str],
    endpoint_filters_configs: str,
) -> RoutingInterface:
    global _router
    _router.reconfigure(
        routing_logic=routing_logic,
        routing_logic_config=routing_logic_config,
        endpoint_filters=endpoint_filters,
        endpoint_filters_configs=endpoint_filters_configs,
    )
    return _router


def get_routing_logic() -> RoutingInterface:
    global _router
    assert _router is not None, (
        "Routing logic not initialized. "
        "Please call initialize_routing_logic() first."
    )
    return _router
