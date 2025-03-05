
from vllm_router.load_metrics.base import BaseLoadMetric
from vllm_router.types import RequestStats, EngineStats

import logging

logger = logging.getLogger(__name__)

class NumQueueingRequest(BaseOverloadDetector):

    def __init__(self, **kwargs):

        if "percentile" not in kwargs:
            logger.warning("Using num_queueing_request overload detector "
            "without specifying percentile in overload detector config."
            "Setting percentile to default value: 0.9")
            percentile = 0.9
        else:
            percentile = kwargs["percentile"]

        self.percentile = percentile

    def get_overload_endpoints(
        self,
        endpoints: Set[str],
        request_stats: Dict[str, RequestStats],
        engine_stats: Dict[str, EngineStats],
    ) -> Set[str]:

        load = [(engine_stats[endpoint].num_queueing_requests, endpoint) for endpoint in endpoints]
        load.sort(key=lambda x: x[0])
        threshold = load[int(len(load) * self.percentile)][0]
        return set([endpoint for _, endpoint in load if _ >= threshold])
