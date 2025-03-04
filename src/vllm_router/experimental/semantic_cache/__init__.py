"""
Experimental semantic cache for the vLLM router.

This module provides semantic caching functionality for LLM requests and responses.
It is considered experimental and may change or be removed at any time.
"""

import logging

from vllm_router.experimental.feature_gates import get_feature_gates
from vllm_router.experimental.semantic_cache.semantic_cache import (
    GetSemanticCache,
    SemanticCache,
    initialize_semantic_cache,
)

logger = logging.getLogger(__name__)

__all__ = [
    "SemanticCache",
    "initialize_semantic_cache",
    "GetSemanticCache",
    "is_semantic_cache_enabled",
    "enable_semantic_cache",
]


# Flag to track if semantic cache is enabled
_semantic_cache_enabled = False


def is_semantic_cache_enabled() -> bool:
    """
    Check if the semantic cache feature is enabled.

    Returns:
        True if the semantic cache feature is enabled, False otherwise
    """
    return _semantic_cache_enabled or get_feature_gates().is_enabled("SemanticCache")


def enable_semantic_cache() -> None:
    """
    Enable the semantic cache feature.
    """
    global _semantic_cache_enabled
    _semantic_cache_enabled = True
    logger.info("Semantic cache feature enabled")
