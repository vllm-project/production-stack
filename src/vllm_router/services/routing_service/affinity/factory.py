import json
from logging import getLogger

from vllm_router.services.routing_service.affinity.base import BaseAffinity

logger = getLogger(__name__)

from vllm_router.services.routing_service.affinity.longest_prefix_affinity import (
    LongestPrefixAffinity,
)
from vllm_router.services.routing_service.affinity.round_robin_affinity import (
    RoundRobinAffinity,
)
from vllm_router.services.routing_service.affinity.session_affinity import (
    SessionAffinity,
)
from vllm_router.services.routing_service.affinity.simhash_affinity import (
    SimhashAffinity,
)

affinity_name_to_class = {
    "round_robin": RoundRobinAffinity,
    "session": SessionAffinity,
    "longest_prefix": LongestPrefixAffinity,
    "simhash": SimhashAffinity,
}


def get_affinity(routing_affinity_name: str, **kwargs) -> BaseAffinity:

    if routing_affinity_name not in affinity_name_to_class:
        raise ValueError(f"Invalid affinity name: {routing_affinity_name}")

    routing_affinity_config = kwargs

    logger.info(
        f"Using affinity type: {routing_affinity_name} with config: {routing_affinity_config}"
    )
    return affinity_name_to_class[routing_affinity_name](**routing_affinity_config)
