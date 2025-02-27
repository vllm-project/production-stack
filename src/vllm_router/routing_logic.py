import abc
import enum
import hashlib
from typing import Dict, List, Optional

from fastapi import Request
from uhashring import HashRing

from vllm_router.engine_stats import EngineStats
from vllm_router.log import init_logger
from vllm_router.request_stats import RequestStats
from vllm_router.service_discovery import EndpointInfo

logger = init_logger(__name__)


class RoutingLogic(str, enum.Enum):
    ROUND_ROBIN = "roundrobin"
    SESSION_BASED = "session"


class SingletonABCMeta(abc.ABCMeta):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


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


class Router(RoutingInterface):
    def __init__(self, affinity: str, overload_detector: str, **kwargs):
        self.affinity = affinity
        self.overload_detector = overload_detector

    def route_request(self, endpoints: List[EndpointInfo], engine_stats: Dict[str, EngineStats], request_stats: Dict[str, RequestStats], request: Request) -> str:
        
        overload_endpoints = self.overload_detector.get_overload_endpoints(endpoints, request_stats, engine_stats)
        self.affinity.update_endpoints_stats(overload_endpoints, engine_stats, request_stats)

        url = self.affinity.get_high_affinity_endpoint(request, request_json, overload_endpoints)

        self.affinity.on_request_routed(url, request_stats, engine_stats)
        
        return url
