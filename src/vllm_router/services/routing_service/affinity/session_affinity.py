from typing import Any, Dict, Set

from fastapi import Request
from uhashring import HashRing

from vllm_router.services.routing_service.affinity.base import BaseAffinity
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats


class SessionAffinity(BaseAffinity):
    def __init__(self, **kwargs):
        if "session_key" not in kwargs:
            raise ValueError(
                "Using session affinity without specifying "
                "session_key in affinity config. Please specify a session_key."
            )

        self.session_key = kwargs["session_key"]
        self.hash_ring = HashRing()
        self.name = "session_affinity"

    def get_high_affinity_endpoint(
        self,
        request: Request,
        request_json: Dict[str, Any],
        available_endpoints: Set[str],
    ) -> str:

        assert available_endpoints.issubset(self.endpoints), (
            f"Available endpoints must be a subset of the endpoints in the hash"
            f"ring. \nAvailable endpoints: {available_endpoints} \n"
            f"Endpoints in hash ring: {self.endpoints}\n"
        )

        session_id = request.headers.get(self.session_key, None)

        for endpoint in self.hash_ring.iterate_nodes(str(session_id), distinct=True):
            if endpoint in available_endpoints:
                return endpoint

        raise ValueError(f"No endpoint found for request: {request}")

    def on_request_routed(
        self, request: Request, request_json: Dict[str, Any], endpoint: str
    ) -> None:
        # Simhash affinity's state is irrelevant to which request
        # is routed to which endpoint.
        pass

    def update_endpoints_stats(
        self,
        endpoints: Set[str],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> None:
        """
        Update the hash ring with the current list of endpoints.
        """
        # Get the current nodes in the hash ring
        current_nodes = set(self.hash_ring.get_nodes())

        # Convert the new endpoint URLs to a set for easy comparison
        new_nodes = endpoints

        # Add new nodes that are not already in the hash ring
        for node in new_nodes - current_nodes:
            self.hash_ring.add_node(node)
