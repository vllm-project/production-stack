
import xxhash
from simhash import Simhash
from uhashring import HashRing
import abc
import enum
import random
from functools import partial
from dataclasses import dataclass
from typing import Set, Callable
from collections import defaultdict, Counter
from fastapi import Request

from vllm_router.affinity.base import BaseAffinity

class HashType(str, enum.Enum):
    XXHASH = "xxhash"
    SIMHASH = "simhash"

    def get_hash_func(self, max_length: int | None = None) -> Callable[[str], int]:
        def trim_and_hash(hash_func: Callable[[str], int], request: str) -> int:
            if max_length is not None:
                request = request[:max_length]
            return hash_func(request)

        base_funcs = {
            HashType.XXHASH: xxhash.xxh64_intdigest,
            HashType.SIMHASH: lambda text: Simhash(text).value
        }

        return partial(trim_and_hash, base_funcs[self])

        
class SimhashAffinity(BaseAffinity):
    def __init__(
        self,
        hash_type: HashType = HashType.SIMHASH,  # The hash function to use for hashing the request
        max_length: int = 512,  # The maximum length of the request to hash
    ):
        self.hash_ring = HashRing()
        self.hash_func = hash_type.get_hash_func(max_length=max_length)
        self.endpoints = set()


    def get_high_affinity_endpoint(
        self,
        request: Request,
        request_json: Dict[str, Any],
        unavailable_endpoints: Set[str],
    ) -> str:

        assert unavailable_endpoints.issubset(self.endpoints)

        messages = json.dumps(request_json["messages"])

        hash_value = self.hash_func(messages)

        # Iterate through nodes starting from the hash position
        for endpoint in self.hash_ring.iterate_nodes(str(hash_value), distinct=True):

            if endpoint not in unavailable_endpoints:
                return endpoint

        raise ValueError(f"No endpoint found for request: {request}")

    def on_request_routed(self, request: Request, request_json: Dict[str, Any], endpoint: str) -> None:
        # In simhash matcher the endpoint state is irrelevant to which request
        # is routed to which endpoint.
        pass

    def update_endpoints_stats(
        self,
        endpoints: Set[str],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> None:

        current_nodes = set(self.hash_ring.get_nodes())

        new_nodes = endpoints

        for node in current_nodes - new_nodes:
            self.hash_ring.remove_node(node)

        for node in new_nodes - current_nodes:
            self.hash_ring.add_node(node)
