"""FastAPI middleware for PII detection."""

import json
import time
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram

from vllm_router.log import init_logger

from .analyzers.base import PIIAnalyzer
from .config import PIIConfig
from .types import PIIType

logger = init_logger(__name__)

# Prometheus metrics
pii_requests_total = Counter(
    "vllm_pii_requests_total", "Total number of requests checked for PII", ["endpoint"]
)

pii_detected_total = Counter(
    "vllm_pii_detected_total",
    "Number of requests where PII was detected",
    ["endpoint", "pii_type"],
)

pii_detection_time = Histogram(
    "vllm_pii_detection_seconds", "Time spent on PII detection", ["endpoint", "status"]
)

pii_detection_score = Histogram(
    "vllm_pii_detection_score", "Confidence scores of PII detection", ["pii_type"]
)

pii_analyzer_errors = Counter(
    "vllm_pii_analyzer_errors_total", "Number of PII analyzer errors", ["error_type"]
)


async def check_pii_content(
    text: str,
    analyzer: PIIAnalyzer,
    config: PIIConfig,
) -> Optional[tuple[bool, set[PIIType]]]:
    """
    Check text content for PII.

    Args:
        text: Text to analyze
        analyzer: PII analyzer instance
        config: PII configuration

    Returns:
        Tuple of (should_block, pii_types) or None if no PII found
    """
    if not text:
        return None

    start_time = time.time()
    try:
        result = await analyzer.analyze(
            text=text,
            pii_types=config.pii_types,
            score_threshold=config.score_threshold,
        )

        duration = time.time() - start_time
        pii_detection_time.labels(endpoint="analyze", status="success").observe(
            duration
        )

        if not result.has_pii:
            logger.debug("No PII detected")
            return None

        # Log detection details with scores
        for loc in result.pii_locations or []:
            logger.info(
                f"PII detected: type={loc.pii_type.value}, "
                f"score={loc.score:.2f}, "
                f"value=<redacted>"
            )
            pii_detection_score.labels(pii_type=loc.pii_type.value).observe(loc.score)

        return True, result.detected_types

    except Exception as e:
        duration = time.time() - start_time
        pii_detection_time.labels(endpoint="analyze", status="error").observe(duration)

        logger.error(f"PII analysis error: {str(e)}")
        pii_analyzer_errors.labels(error_type=type(e).__name__).inc()

        # Conservative approach: block on error
        return True, set()


async def check_pii(
    request: Request,
    analyzer: PIIAnalyzer,
    config: Optional[PIIConfig] = None,
) -> Optional[JSONResponse]:
    """
    Check request for PII and take appropriate action.

    Args:
        request: The FastAPI request
        analyzer: PII analyzer instance
        config: Optional PII detection configuration

    Returns:
        JSONResponse if request should be blocked, None if request can proceed
    """
    if not config or not config.enabled:
        return None

    try:
        body = await request.json()

        # Extract text to analyze from request body
        text_to_analyze = json.dumps(body)

        result = await check_pii_content(text_to_analyze, analyzer, config)
        if not result:
            return None

        should_block, pii_types = result

        if should_block:
            # Increment metrics
            for pii_type in pii_types:
                pii_detected_total.labels(
                    endpoint=request.url.path, pii_type=pii_type.value
                ).inc()

            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "PII detected in request",
                        "types": [t.value for t in pii_types],
                    }
                },
            )

        return None

    except Exception as e:
        logger.error(f"Error in PII middleware: {str(e)}")
        pii_analyzer_errors.labels(error_type=type(e).__name__).inc()
        return None
