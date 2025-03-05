
from vllm_router.overload_detectors.base import BaseOverloadDetector

import json
from logging import getLogger

logger = getLogger(__name__)

from vllm_router.overload_detector.num_queued_requests import NumQueuedRequestsOverloadDetector

overload_detector_str_to_class = {
    "num_queued_requests": NumQueuedRequestsOverloadDetector,
}

def get_overload_detector(overload_detector_type: str, overload_detector_config: str) -> BaseOverloadDetector:
    if overload_detector_type not in overload_detector_str_to_class:
        raise ValueError(f"Invalid overload detector type: {overload_detector_type}")

    kwargs = json.loads(overload_detector_config)
    logger.info(f"Using overload detector type: {overload_detector_type} with config: {kwargs}")
    return overload_detector_str_to_class[overload_detector_type](**kwargs)
