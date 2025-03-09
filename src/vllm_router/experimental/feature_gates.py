"""Feature gates for experimental features."""

import json
import logging
import os
from enum import Enum
from typing import Dict, Optional, Set

from vllm_router.utils import SingletonMeta

logger = logging.getLogger(__name__)

# Feature gate names
SEMANTIC_CACHE = "SemanticCache"
PII_DETECTION = "PIIDetection"  # Add PII detection feature gate


class FeatureStage(Enum):
    """
    Defines the stage of a feature.

    ALPHA: Feature is in early development and may change or be removed at any time.
    BETA: Feature is well tested but not considered stable yet.
    GA: Feature is stable and will not be removed.
    """

    ALPHA = "Alpha"
    BETA = "Beta"
    GA = "GA"


class Feature:
    """
    Represents a feature with its name, description, and stage.
    """

    def __init__(
        self,
        name: str,
        description: str,
        stage: FeatureStage,
        default_enabled: bool = False,
    ):
        self.name = name
        self.description = description
        self.stage = stage
        self.default_enabled = default_enabled


class FeatureGates(metaclass=SingletonMeta):
    """Manages feature gates for experimental features."""

    def __init__(self):
        """Initialize feature gates."""
        self._enabled_features: Set[str] = set()

    def enable(self, feature: str) -> None:
        """Enable a feature."""
        self._enabled_features.add(feature)
        logger.info(f"Enabled feature: {feature}")

    def disable(self, feature: str) -> None:
        """Disable a feature."""
        self._enabled_features.discard(feature)
        logger.info(f"Disabled feature: {feature}")

    def is_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled."""
        return feature in self._enabled_features

    def configure(self, config: Dict[str, bool]) -> None:
        """Configure multiple features at once."""
        for feature, enabled in config.items():
            if enabled:
                self.enable(feature)
            else:
                self.disable(feature)


def initialize_feature_gates(config: Optional[str] = None) -> None:
    """
    Initialize feature gates from a configuration string.

    Args:
        config: Configuration string in the format "feature1=true,feature2=false"
    """
    feature_gates = get_feature_gates()

    if not config:
        return

    try:
        # Parse config string
        features = {}
        for item in config.split(","):
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            features[name.strip()] = value.strip().lower() == "true"

        # Configure feature gates
        feature_gates.configure(features)

    except Exception as e:
        logger.error(f"Failed to initialize feature gates: {e}")
        raise


def get_feature_gates() -> FeatureGates:
    """Get the feature gates singleton."""
    return FeatureGates()


def initialize_feature_gates(feature_gates_str: Optional[str] = None):
    """
    Initialize the feature gates system.

    Args:
        feature_gates_str: Optional comma-separated list of feature gates
    """
    feature_gates = get_feature_gates()

    # Parse environment variable if it exists
    env_feature_gates = os.environ.get("VLLM_FEATURE_GATES")
    if env_feature_gates:
        feature_gates.configure(
            dict(map(lambda x: x.split("="), env_feature_gates.split(",")))
        )

    # Parse command-line argument if provided
    if feature_gates_str:
        feature_gates.configure(
            dict(map(lambda x: x.split("="), feature_gates_str.split(",")))
        )

    # Log enabled features
    enabled_features = [name for name in feature_gates._enabled_features]
    if enabled_features:
        logger.info(f"Enabled experimental features: {', '.join(enabled_features)}")
    else:
        logger.info("No experimental features enabled")
