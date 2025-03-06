"""
    Abstract class for best endpoint selector.
"""

import abc
from typing import Set, Dict
from vllm_router.types import EngineStats, RequestStats

class BaseAffinityMaintainer(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_high_affinity_endpoint(
        self,
        request: Request,
        request_json: Dict[str, Any],
        unavailable_endpoints: Set[str] = set(),
    ) -> str:
        """
        Get the endpoint with the highest affinity for the request.
        If there are multiple endpoints with the same affinity, return one of them randomly.

        Args:
            request (Request): The request.
            request_json (Dict[str, Any]): The jsonized request body.
            unavailable_endpoints (Set[str]): The endpoints that are temporarily unavailable.

        Returns:
            str: The endpoint with the highest affinity for the request.
        """
        pass

    @abc.abstractmethod
    def on_request_routed(
        self,
        request: Request,
        request_json: Dict[str, Any],
        endpoint: str,
    ) -> None:
        """
        Notify the affinity maintainer that the request is actually routed to the endpoint.

        Args:
            request (Request): The request.
            request_json (Dict[str, Any]): The jsonized request body.
            endpoint (str): The endpoint that is actually routed to.
        """
        pass

    @abc.abstractmethod
    def update_endpoints_stats(
        self,
        endpoints: Set[str],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> None:
        """
        Update the endpoint stats. This will not remove any endpoints.
        """
        pass
