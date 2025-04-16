import abc
from dataclasses import dataclass
from typing import Dict, Set

from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats


class BaseEndpointFilter(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_filtered_endpoints(
        self,
        endpoints: Set[str],
        request_stats: Dict[str, RequestStats],
        engine_stats: Dict[str, EngineStats],
    ) -> Set[str]:
        """
        Filter the endpoints based on the request stats and engine stats.
        """
        pass
