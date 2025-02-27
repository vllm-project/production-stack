
from dataclasses import dataclass
from typing import Set, Dict
import abc

class BaseOverloadDetector(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def get_overload_endpoints(
        self,
        endpoints: Set[str],
        request_stats: Dict[str, RequestStats],
        engine_stats: Dict[str, EngineStats],
    ) -> Set[str]:
        """
        Check if the endpoint is overloaded.
        """
        pass