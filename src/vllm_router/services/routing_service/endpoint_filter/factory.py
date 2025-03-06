
from vllm_router.services.routing_service.endpoint_filter.base import BaseEndpointFilter

import json
from logging import getLogger

logger = getLogger(__name__)

from vllm_router.services.routing_service.endpoint_filter.num_queueing_request_filter import NumQueueingRequestFilter

endpoint_filter_name_to_class = {
    "num_queueing_request_filter": NumQueueingRequestFilter,
}

def get_endpoint_filter(endpoint_filter_name: str, endpoint_filter_config: Dict[str, Any] = {}, **kwargs) -> BaseEndpointFilter:
    if endpoint_filter_name not in endpoint_filter_name_to_class:
        raise ValueError(f"Invalid endpoint filter name: {endpoint_filter_name}")

    assert kwargs == {}, ("There are extra kwargs forwarded to the endpoint filter "
                           "factory method. This is likely unintended. "
                           "Received kwargs: %s" % kwargs)

    logger.info(f"Using endpoint filter type: {endpoint_filter_name} with config: {endpoint_filter_config}")
    return endpoint_filter_name_to_class[endpoint_filter_name](**endpoint_filter_config)
