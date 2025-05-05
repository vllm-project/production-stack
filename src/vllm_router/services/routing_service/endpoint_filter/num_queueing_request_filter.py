import logging
from typing import Dict, Set

from vllm_router.services.routing_service.endpoint_filter.base import BaseEndpointFilter
from vllm_router.stats.engine_stats import EngineStats
from vllm_router.stats.request_stats import RequestStats

logger = logging.getLogger(__name__)


class NumQueueingRequestFilter(BaseEndpointFilter):

    def __init__(self, **kwargs):

        if "percentile" not in kwargs:
            logger.warning(
                "Using num_queueing_request endpoint filter "
                "without specifying percentile in endpoint filter config."
                "Setting percentile to default value: 0.9"
            )
            percentile = 0.9
        else:
            percentile = kwargs["percentile"]

        self.percentile = percentile
        self.name = "num_queueing_request_filter"

    def get_filtered_endpoints(
        self,
        endpoints: Set[str],
        request_stats: Dict[str, RequestStats],
        engine_stats: Dict[str, EngineStats],
    ) -> Set[str]:

        load = [
            (engine_stats[endpoint].num_queueing_requests, endpoint)
            for endpoint in endpoints
        ]
        load.sort(key=lambda x: x[0])
        threshold = load[int(len(load) * self.percentile)][0]
        return set([endpoint for _, endpoint in load if _ >= threshold])
