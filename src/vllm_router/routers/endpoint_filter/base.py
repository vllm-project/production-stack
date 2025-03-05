
from dataclasses import dataclass
from typing import Set, Dict
import abc

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
