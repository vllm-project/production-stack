"""Factory for creating PII analyzers."""

import logging
from typing import Dict, Optional, Type

from .base import PIIAnalyzer
from .presidio import PresidioAnalyzer
from .regex import RegexAnalyzer

logger = logging.getLogger(__name__)

# Registry of available analyzers
ANALYZERS: Dict[str, Type[PIIAnalyzer]] = {
    "presidio": PresidioAnalyzer,
    "regex": RegexAnalyzer,
}


async def create_analyzer(
    analyzer_type: str, config: Optional[Dict] = None
) -> PIIAnalyzer:
    """
    Create and initialize a PII analyzer.

    Args:
        analyzer_type: Type of analyzer to create
        config: Optional configuration for the analyzer

    Returns:
        Initialized PII analyzer

    Raises:
        ValueError: If analyzer_type is not supported
        RuntimeError: If analyzer initialization fails
    """
    if analyzer_type not in ANALYZERS:
        raise ValueError(
            f"Unsupported analyzer type: {analyzer_type}. "
            f"Supported types: {list(ANALYZERS.keys())}"
        )

    try:
        # Create analyzer instance
        analyzer_class = ANALYZERS[analyzer_type]
        analyzer = analyzer_class(config)

        # Initialize it
        await analyzer.initialize()

        logger.info(f"Created and initialized {analyzer_type} analyzer")
        return analyzer

    except Exception as e:
        logger.error(f"Failed to create {analyzer_type} analyzer: {e}")
        raise RuntimeError(f"Failed to create {analyzer_type} analyzer") from e
