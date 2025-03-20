"""Base interface for PII analyzers."""

import abc
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from ..types import PIIType


@dataclass
class PIILocation:
    """Location of PII in text."""

    start: int  # Start index in text
    end: int  # End index in text
    pii_type: PIIType  # Type of PII found
    value: str  # The actual PII text found
    score: float  # Confidence score of the detection


@dataclass
class PIIAnalysisResult:
    """Result of PII analysis."""

    has_pii: bool  # Whether PII was found
    detected_types: Set[PIIType]  # Types of PII found
    pii_locations: Optional[List[PIILocation]] = None  # Locations of PII in text


class PIIAnalyzer(abc.ABC):
    """Base class for PII analyzers."""

    def __init__(self, config: Optional[Dict] = None):
        """Initialize the analyzer with optional config."""
        self.config = config or {}

    @abc.abstractmethod
    async def analyze(
        self,
        text: str,
        pii_types: Optional[Set[PIIType]] = None,
        score_threshold: float = 0.5,
    ) -> PIIAnalysisResult:
        """
        Analyze text for PII.

        Args:
            text: Text to analyze
            pii_types: Types of PII to look for. If None, look for all types.
            score_threshold: Minimum confidence score to consider a match

        Returns:
            PIIAnalysisResult containing analysis results
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialize the analyzer. Called once before first use."""
        raise NotImplementedError

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the analyzer. Called when service is shutting down."""
        raise NotImplementedError
