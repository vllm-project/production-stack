
from vllm_router.affinity.base import BaseAffinity
from vllm_router.overload_detectors.base import BaseOverloadDetector

import json
from logging import getLogger

logger = getLogger(__name__)

from vllm_router.affinity.round_robin_affinity import RoundRobinAffinity
from vllm_router.affinity.session_based_affinity import SessionBasedAffinity
from vllm_router.affinity.longest_prefix_affinity import LongestPrefixAffinity
from vllm_router.affinity.simhash_affinity import SimhashAffinity

affinity_str_to_class = {
    "round_robin": RoundRobinAffinity,
    "session": SessionBasedAffinity,
    "longest_prefix": LongestPrefixAffinity,
    "simhash": SimhashAffinity,
}

def get_affinity(affinity_type: str, affinity_config: str) -> BaseAffinity:
    if affinity_type not in affinity_str_to_class:
        raise ValueError(f"Invalid affinity type: {affinity_type}")

    kwargs = json.loads(affinity_config)
    logger.info(f"Using affinity type: {affinity_type} with config: {kwargs}")
    return affinity_str_to_class[affinity_type](**kwargs)
