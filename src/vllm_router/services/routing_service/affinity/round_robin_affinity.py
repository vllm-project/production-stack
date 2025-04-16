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


class RoundRobinAffinity(BaseAffinity):
    def __init__(self, **kwargs):
        self.index = 0
        self.name = "round_robin_affinity"

    def get_high_affinity_endpoint(
        self,
        request: Request,
        request_json: Dict[str, Any],
        available_endpoints: Set[str],
    ) -> str:
        if not available_endpoints:
            raise ValueError(f"No available endpoints for request: {request}")

        available_endpoints = list(available_endpoints)
        endpoint = available_endpoints[self.index % len(available_endpoints)]
        self.index = self.index + 1
        return endpoint

    def on_request_routed(
        self, request: Request, request_json: Dict[str, Any], endpoint: str
    ) -> None:
        pass

    def update_endpoints_stats(
        self,
        endpoints: Set[str],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
    ) -> None:
        pass
