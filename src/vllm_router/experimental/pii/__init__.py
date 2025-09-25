"""PII detection module for vLLM router."""

import logging
from typing import Optional

from .analyzers.base import PIIAnalyzer
from .analyzers.factory import create_analyzer
from .config import PIIConfig
from .middleware import check_pii
from .types import PIIAction, PIITarget, PIIType

logger = logging.getLogger(__name__)

# Global analyzer instance
_analyzer: Optional[PIIAnalyzer] = None


async def initialize_pii_detection(
    analyzer_type: str = "presidio", config: Optional[dict] = None
) -> None:
    """
    Initialize PII detection with the specified analyzer.

    Args:
        analyzer_type: Type of analyzer to use
        config: Optional configuration for the analyzer
    """
    global _analyzer

    try:
        _analyzer = await create_analyzer(analyzer_type, config)
        logger.info(f"Initialized PII detection with {analyzer_type} analyzer")
    except Exception as e:
        logger.error(f"Failed to initialize PII detection: {e}")
        raise


async def shutdown_pii_detection() -> None:
    """Shutdown PII detection."""
    global _analyzer

    if _analyzer:
        await _analyzer.shutdown()
        _analyzer = None
        logger.info("Shut down PII detection")


def get_pii_analyzer() -> Optional[PIIAnalyzer]:
    """Get the current PII analyzer instance."""
    return _analyzer


def is_pii_detection_enabled() -> bool:
    """Check if PII detection is enabled."""
    return _analyzer is not None


__all__ = [
    "PIIAction",
    "PIITarget",
    "PIIType",
    "PIIConfig",
    "check_pii",
    "initialize_pii_detection",
    "shutdown_pii_detection",
    "get_pii_analyzer",
    "is_pii_detection_enabled",
]
