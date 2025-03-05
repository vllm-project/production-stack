"""Configuration for PII detection."""

from dataclasses import dataclass
from typing import Optional, Set

from .types import PIIType


@dataclass
class PIIConfig:
    """Configuration for PII detection."""

    # Whether PII detection is enabled
    enabled: bool = True

    # Types of PII to detect
    # If None, detect all types
    pii_types: Optional[Set[PIIType]] = None

    # Analyzer-specific configuration
    score_threshold: float = 0.5

    @staticmethod
    def from_dict(config_dict: dict) -> "PIIConfig":
        """Create a PIIConfig from a dictionary."""
        enabled = config_dict.get("enabled", True)

        pii_types = None
        if "pii_types" in config_dict:
            pii_types = {PIIType(t) for t in config_dict["pii_types"]}

        score_threshold = config_dict.get("score_threshold", 0.5)

        return PIIConfig(
            enabled=enabled, pii_types=pii_types, score_threshold=score_threshold
        )

    def to_dict(self) -> dict:
        """Convert the config to a dictionary."""
        return {
            "enabled": self.enabled,
            "pii_types": [t.value for t in self.pii_types] if self.pii_types else None,
            "score_threshold": self.score_threshold,
        }
