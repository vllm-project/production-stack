import abc
import enum
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Dict, Set

import xxhash
from fastapi import Request
from simhash import Simhash
from uhashring import HashRing

from vllm_router.services.routing_service.affinity.base import BaseAffinity
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats


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
            HashType.SIMHASH: lambda text: Simhash(text).value,
        }

        return partial(trim_and_hash, base_funcs[self])


class SimhashAffinity(BaseAffinity):
    def __init__(self, **kwargs):

        if "hash_type" not in kwargs:
            logger.warning(
                "Using simhash affinity without hash_type."
                "Setting hash_type to default value: SIMHASH"
            )
            hash_type = HashType.SIMHASH
        else:
            hash_type = getattr(HashType, kwargs["hash_type"])

        if "max_length" not in kwargs:
            logger.warning(
                "Using simhash affinity without max_length."
                "Setting max_length to default value: 512"
            )
            max_length = 512
        else:
            max_length = kwargs["max_length"]

        self.hash_ring = HashRing()
        self.hash_func = hash_type.get_hash_func(max_length=max_length)
        self.endpoints = set()
        self.name = "simhash_affinity"

    def get_high_affinity_endpoint(
        self,
        request: Request,
        request_json: Dict[str, Any],
        available_endpoints: Set[str],
    ) -> str:

        assert available_endpoints.issubset(self.endpoints)

        messages = json.dumps(request_json["messages"])

        hash_value = self.hash_func(messages)

        # Iterate through nodes starting from the hash position
        for endpoint in self.hash_ring.iterate_nodes(str(hash_value), distinct=True):

            if endpoint in available_endpoints:
                return endpoint

        raise ValueError(f"No endpoint found for request: {request}")

    def on_request_routed(
        self, request: Request, request_json: Dict[str, Any], endpoint: str
    ) -> None:
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

        for node in new_nodes - current_nodes:
            self.hash_ring.add_node(node)
