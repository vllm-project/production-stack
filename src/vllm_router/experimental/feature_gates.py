import logging
import os
from enum import Enum
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)


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


class FeatureGates:
    """
    Manages experimental features through feature gates.
    Similar to Kubernetes feature gates, this allows explicit enabling/disabling of features.
    """

    _instance = None

    def __init__(self):
        # Dictionary of all available features
        self.available_features: Dict[str, Feature] = {}

        # Set of enabled features
        self.enabled_features: Set[str] = set()

        # Register all known features
        self._register_known_features()

    def _register_known_features(self):
        """Register all known features with their default states."""
        self.register_feature(
            Feature(
                name="SemanticCache",
                description="Semantic caching of LLM requests and responses",
                stage=FeatureStage.ALPHA,
                default_enabled=False,
            )
        )

    def register_feature(self, feature: Feature):
        """
        Register a new feature.

        Args:
            feature: The feature to register
        """
        self.available_features[feature.name] = feature
        if feature.default_enabled:
            self.enabled_features.add(feature.name)

    def enable_feature(self, feature_name: str) -> bool:
        """
        Enable a feature by name.

        Args:
            feature_name: The name of the feature to enable

        Returns:
            True if the feature was enabled, False if it doesn't exist
        """
        if feature_name in self.available_features:
            self.enabled_features.add(feature_name)
            logger.info(f"Feature '{feature_name}' enabled")
            return True
        logger.warning(f"Attempted to enable unknown feature '{feature_name}'")
        return False

    def disable_feature(self, feature_name: str) -> bool:
        """
        Disable a feature by name.

        Args:
            feature_name: The name of the feature to disable

        Returns:
            True if the feature was disabled, False if it doesn't exist
        """
        if feature_name in self.available_features:
            self.enabled_features.discard(feature_name)
            logger.info(f"Feature '{feature_name}' disabled")
            return True
        logger.warning(f"Attempted to disable unknown feature '{feature_name}'")
        return False

    def is_enabled(self, feature_name: str) -> bool:
        """
        Check if a feature is enabled.

        Args:
            feature_name: The name of the feature to check

        Returns:
            True if the feature is enabled, False otherwise
        """
        return feature_name in self.enabled_features

    def parse_feature_gates(self, feature_gates_str: str):
        """
        Parse a comma-separated list of feature gates.

        Format: feature1=true,feature2=false

        Args:
            feature_gates_str: The feature gates string to parse
        """
        if not feature_gates_str:
            return

        for gate in feature_gates_str.split(","):
            if "=" not in gate:
                logger.warning(f"Invalid feature gate format: {gate}")
                continue

            name, value = gate.split("=", 1)
            name = name.strip()
            value = value.strip().lower()

            if value in ("true", "yes", "1"):
                self.enable_feature(name)
            elif value in ("false", "no", "0"):
                self.disable_feature(name)
            else:
                logger.warning(f"Invalid feature gate value: {value}")

    def list_features(self) -> Dict[str, Dict]:
        """
        List all available features and their status.

        Returns:
            A dictionary of feature information
        """
        result = {}
        for name, feature in self.available_features.items():
            result[name] = {
                "description": feature.description,
                "stage": feature.stage.value,
                "enabled": name in self.enabled_features,
            }
        return result


def get_feature_gates() -> FeatureGates:
    """
    Get the singleton instance of FeatureGates.

    Returns:
        The FeatureGates instance
    """
    if FeatureGates._instance is None:
        FeatureGates._instance = FeatureGates()
    return FeatureGates._instance


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
        feature_gates.parse_feature_gates(env_feature_gates)

    # Parse command-line argument if provided
    if feature_gates_str:
        feature_gates.parse_feature_gates(feature_gates_str)

    # Log enabled features
    enabled_features = [name for name in feature_gates.enabled_features]
    if enabled_features:
        logger.info(f"Enabled experimental features: {', '.join(enabled_features)}")
    else:
        logger.info("No experimental features enabled")
