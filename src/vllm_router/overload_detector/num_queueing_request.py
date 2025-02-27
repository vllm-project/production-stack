
from vllm_router.load_metrics.base import BaseLoadMetric
from vllm_router.types import RequestStats, EngineStats

class NumQueueingRequest(BaseOverloadDetector):

    def __init__(self, percentile: float = 0.9, **kwargs):
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
