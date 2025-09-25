"""Regex-based PII analyzer implementation."""

import logging
import re
from typing import Dict, Optional, Set

from ..types import PIIType
from .base import PIIAnalysisResult, PIIAnalyzer, PIILocation

logger = logging.getLogger(__name__)

# Regex patterns for different PII types
PII_PATTERNS = {
    PIIType.EMAIL: r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    PIIType.PHONE: r"\b(?:\+?1[-.]?)?\s*(?:\([0-9]{3}\)|[0-9]{3})[-.]?[0-9]{3}[-.]?[0-9]{4}\b",
    PIIType.SSN: r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b",
    PIIType.CREDIT_CARD: r"\b(?:\d[ -]*?){13,16}\b",
    PIIType.IP_ADDRESS: r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}


class RegexAnalyzer(PIIAnalyzer):
    """PII analyzer using regular expressions."""

    def __init__(self, config: Optional[Dict] = None):
        """Initialize the analyzer with optional config."""
        super().__init__(config)
        self.patterns = {}

    async def initialize(self) -> None:
        """Initialize regex patterns."""
        try:
            # Compile regex patterns
            self.patterns = {
                pii_type: re.compile(pattern)
                for pii_type, pattern in PII_PATTERNS.items()
            }
            logger.info("Initialized Regex analyzer successfully")
        except Exception as e:
            error_msg = f"Failed to initialize Regex analyzer: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def shutdown(self) -> None:
        """Shutdown the analyzer."""
        self.patterns = {}

    async def analyze(
        self,
        text: str,
        pii_types: Optional[Set[PIIType]] = None,
        score_threshold: float = 0.5,
    ) -> PIIAnalysisResult:
        """Analyze text for PII using regex patterns."""
        if not self.patterns:
            raise RuntimeError("Analyzer not initialized. Call initialize() first.")

        try:
            detected_types = set()
            pii_locations = []

            # Determine which patterns to use
            patterns_to_check = (
                {t: self.patterns[t] for t in pii_types if t in self.patterns}
                if pii_types
                else self.patterns
            )

            # Search for each pattern
            for pii_type, pattern in patterns_to_check.items():
                for match in pattern.finditer(text):
                    detected_types.add(pii_type)
                    pii_locations.append(
                        PIILocation(
                            start=match.start(),
                            end=match.end(),
                            pii_type=pii_type,
                            value=match.group(),
                            score=1.0,  # Regex matches are binary - either match or no match
                        )
                    )

            return PIIAnalysisResult(
                has_pii=bool(detected_types),
                detected_types=detected_types,
                pii_locations=pii_locations if pii_locations else None,
            )

        except Exception as e:
            error_msg = f"Error analyzing text with Regex analyzer: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
