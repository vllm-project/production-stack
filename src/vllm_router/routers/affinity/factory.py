
from vllm_router.routers.affinity.base import BaseAffinity

import json
from logging import getLogger

logger = getLogger(__name__)

from vllm_router.affinity.round_robin_affinity import RoundRobinAffinity
from vllm_router.affinity.session_based_affinity import SessionBasedAffinity
from vllm_router.affinity.longest_prefix_affinity import LongestPrefixAffinity
from vllm_router.affinity.simhash_affinity import SimhashAffinity

affinity_name_to_class = {
    "round_robin": RoundRobinAffinity,
    "session": SessionBasedAffinity,
    "longest_prefix": LongestPrefixAffinity,
    "simhash": SimhashAffinity,
}

def get_affinity(affinity_name: str, affinity_config: Dict[str, Any] = {}, **kwargs) -> BaseAffinity:

    if affinity_name not in affinity_name_to_class:
        raise ValueError(f"Invalid affinity name: {affinity_name}")


    assert kwargs == {}, ("There are extra kwargs forwarded to the affinity "
                           "factory method. This is likely unintended. "
                           "Received kwargs: %s" % kwargs)

    logger.info(f"Using affinity type: {affinity_name} with config: {affinity_config}")
    return affinity_name_to_class[affinity_name](**affinity_config)
