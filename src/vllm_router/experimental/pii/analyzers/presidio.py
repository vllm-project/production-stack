"""Presidio-based PII analyzer implementation."""

import logging
from typing import Dict, Optional, Set

from ..types import PIIType
from .base import PIIAnalysisResult, PIIAnalyzer, PIILocation

# Check for dependencies
MISSING_DEPS = []

try:
    import pydantic

    pydantic_version = tuple(map(int, pydantic.__version__.split(".")))
    if pydantic_version < (2, 0, 0):
        MISSING_DEPS.append("pydantic>=2.0.0")
except ImportError:
    MISSING_DEPS.append("pydantic>=2.0.0")


try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
except ImportError:
    MISSING_DEPS.append("presidio-analyzer>=2.2.0")


logger = logging.getLogger(__name__)

# Mapping from our PII types to Presidio entity types
PII_TO_PRESIDIO = {
    PIIType.EMAIL: "EMAIL_ADDRESS",
    PIIType.PHONE: "PHONE_NUMBER",
    PIIType.SSN: "US_SSN",
    PIIType.CREDIT_CARD: "CREDIT_CARD",
    PIIType.IP_ADDRESS: "IP_ADDRESS",
    PIIType.API_KEY: "API_KEY",
}

# Reverse mapping
PRESIDIO_TO_PII = {v: k for k, v in PII_TO_PRESIDIO.items()}


class PresidioAnalyzer(PIIAnalyzer):
    """PII analyzer using Microsoft Presidio."""

    def __init__(self, config: Optional[Dict] = None):
        """Initialize the analyzer with optional config."""
        super().__init__(config)
        self.analyzer = None

    async def initialize(self) -> None:
        """Initialize Presidio analyzer."""
        if MISSING_DEPS:
            deps_msg = []
            pip_deps = [d for d in MISSING_DEPS if not d.startswith("python")]
            spacy_deps = [d for d in MISSING_DEPS if d.startswith("python")]

            if pip_deps:
                deps_msg.append(f"pip install {' '.join(pip_deps)}")
            if spacy_deps:
                deps_msg.extend(spacy_deps)

            error_msg = (
                "Missing required dependencies for PII detection. "
                "Please run the following commands:\n" + "\n".join(deps_msg)
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        try:
            # Initialize NLP engine with configuration
            nlp_configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }

            # Create NLP engine provider with configuration
            provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
            nlp_engine = provider.create_engine()

            # Create analyzer
            self.analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine, supported_languages=["en"]
            )
            logger.info("Initialized Presidio analyzer successfully")

        except Exception as e:
            error_msg = (
                f"Failed to initialize Presidio analyzer: {str(e)}\n"
                "This might be due to incompatible package versions. "
                "Please ensure you have installed the correct versions:\n"
                "pip install -r src/vllm_router/experimental/pii/requirements.txt"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def shutdown(self) -> None:
        """Shutdown the analyzer."""
        self.analyzer = None

    async def analyze(
        self,
        text: str,
        pii_types: Optional[Set[PIIType]] = None,
        score_threshold: float = 0.5,
    ) -> PIIAnalysisResult:
        """Analyze text for PII using Presidio."""
        if not self.analyzer:
            raise RuntimeError("Analyzer not initialized. Call initialize() first.")

        try:
            # Convert our PII types to Presidio entity types
            entities = None
            if pii_types:
                entities = [
                    PII_TO_PRESIDIO[t] for t in pii_types if t in PII_TO_PRESIDIO
                ]

            # Analyze text with Presidio
            results = self.analyzer.analyze(
                text=text,
                language="en",
                entities=entities,
                score_threshold=score_threshold,
            )

            # Convert Presidio results to our format
            detected_types = set()
            pii_locations = []

            for result in results:
                # Skip if entity type not in our mapping
                if result.entity_type not in PRESIDIO_TO_PII:
                    continue

                pii_type = PRESIDIO_TO_PII[result.entity_type]
                detected_types.add(pii_type)

                pii_locations.append(
                    PIILocation(
                        start=result.start,
                        end=result.end,
                        pii_type=pii_type,
                        value=text[result.start : result.end],
                        score=result.score,
                    )
                )

            return PIIAnalysisResult(
                has_pii=bool(detected_types),
                detected_types=detected_types,
                pii_locations=pii_locations if pii_locations else None,
            )

        except Exception as e:
            error_msg = f"Error analyzing text with Presidio: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
