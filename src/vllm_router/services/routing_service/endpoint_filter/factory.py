import json
from logging import getLogger

from vllm_router.services.routing_service.endpoint_filter.base import BaseEndpointFilter

logger = getLogger(__name__)

from vllm_router.services.routing_service.endpoint_filter.num_queueing_request_filter import (
    NumQueueingRequestFilter,
)

endpoint_filter_name_to_class = {
    "num_queueing_request": NumQueueingRequestFilter,
}


def get_endpoint_filter(endpoint_filter_name: str, **kwargs) -> BaseEndpointFilter:
    if endpoint_filter_name not in endpoint_filter_name_to_class:
        raise ValueError(f"Invalid endpoint filter name: {endpoint_filter_name}")

    logger.info(
        f"Using endpoint filter type: {endpoint_filter_name} with config: {kwargs}"
    )
    return endpoint_filter_name_to_class[endpoint_filter_name](**kwargs)
