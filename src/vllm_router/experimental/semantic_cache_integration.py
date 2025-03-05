"""
Integration of the experimental semantic cache with the vLLM router.

This module provides functions to integrate the semantic cache with the vLLM router.
"""

import argparse
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from prometheus_client import Gauge

from vllm_router.experimental.semantic_cache import (
    GetSemanticCache,
    is_semantic_cache_enabled,
)

logger = logging.getLogger("uvicorn")

# Prometheus metrics for semantic cache
semantic_cache_hits = Gauge(
    "vllm:semantic_cache_hits", "Number of semantic cache hits", ["server"]
)
semantic_cache_misses = Gauge(
    "vllm:semantic_cache_misses", "Number of semantic cache misses", ["server"]
)
semantic_cache_hit_ratio = Gauge(
    "vllm:semantic_cache_hit_ratio",
    "Ratio of semantic cache hits to total lookups",
    ["server"],
)
semantic_cache_size = Gauge(
    "vllm:semantic_cache_size", "Number of entries in the semantic cache", ["server"]
)
semantic_cache_latency = Gauge(
    "vllm:semantic_cache_latency",
    "Average latency for semantic cache lookups",
    ["server"],
)


def add_semantic_cache_args(parser: argparse.ArgumentParser) -> None:
    """
    Add semantic cache command-line arguments to the argument parser.

    Args:
        parser: The argument parser to add arguments to
    """
    parser.add_argument(
        "--semantic-cache-model",
        type=str,
        default="all-MiniLM-L6-v2",
        help="Sentence transformer model to use for semantic cache embeddings",
    )
    parser.add_argument(
        "--semantic-cache-dir",
        type=str,
        default="semantic_cache",
        help="Directory to store semantic cache files in",
    )
    parser.add_argument(
        "--semantic-cache-threshold",
        type=float,
        default=0.95,
        help="Default similarity threshold for semantic cache hits",
    )


async def store_in_semantic_cache(
    endpoint: str, method: str, body: bytes, chunk: bytes
) -> None:
    """
    Store a request and response in the semantic cache if conditions are met.

    Args:
        endpoint: The API endpoint that was called
        method: The HTTP method used
        body: The request body
        chunk: The response body chunk (may not be complete JSON)
    """
    # Check if semantic cache is enabled via feature gates
    if not is_semantic_cache_enabled():
        logger.debug("Semantic cache is not enabled, skipping store operation")
        return

    # If this is a chat completion request and semantic cache is enabled,
    # store the request and response in the cache
    semantic_cache = GetSemanticCache()
    if semantic_cache and endpoint == "/v1/chat/completions" and method == "POST":
        logger.info("Processing chat completion for potential caching")
        try:
            # Parse the request body
            request_body = json.loads(body)

            # Skip caching if requested
            if request_body.get("skip_cache", False):
                logger.info("Skipping cache storage due to skip_cache flag")
                return

            # For streaming responses, we can't reliably cache from chunks
            # as they may not contain complete JSON
            if request_body.get("stream", False):
                logger.info("Skipping cache storage for streaming response")
                return

            # Try to parse the response chunk as JSON, but handle errors gracefully
            try:
                response_body = json.loads(chunk)
            except json.JSONDecodeError:
                logger.warning(
                    "Cannot parse response chunk as JSON, skipping cache storage"
                )
                return

            # Extract the necessary information
            model = request_body.get("model", "")
            request_messages = request_body.get("messages", [])

            # Log request details
            logger.info(f"Preparing to cache response for model: {model}")
            if request_messages and len(request_messages) > 0:
                first_msg = request_messages[0]
                content = first_msg.get("content", "")
                logger.info(
                    f"Request first message ({first_msg.get('role', 'user')}): {content[:50]}..."
                )

            # Extract response messages and usage from the response
            response_messages = []
            if "choices" in response_body:
                for choice in response_body["choices"]:
                    if "message" in choice:
                        response_messages.append(choice["message"])

            usage = response_body.get(
                "usage",
                {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

            # Log response details
            if response_messages and len(response_messages) > 0:
                first_resp = response_messages[0]
                content = first_resp.get("content", "")
                logger.info(f"Response first message: {content[:50]}...")

            logger.info(f"Response usage: {usage}")

            # Store in the cache
            logger.info("Storing response in semantic cache")
            success = semantic_cache.store(
                request_messages=request_messages,
                response_messages=response_messages,
                model=model,
                usage=usage,
            )

            # Update the cache size metric if store was successful
            if (
                success
                and hasattr(semantic_cache, "db")
                and hasattr(semantic_cache.db, "index")
            ):
                semantic_cache_size.labels(server="router").set(
                    semantic_cache.db.index.ntotal
                )
                logger.info(
                    f"Updated cache size metric: {semantic_cache.db.index.ntotal} entries"
                )
        except Exception as e:
            logger.error(f"Error storing in semantic cache: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())


async def check_semantic_cache(request: Request) -> Optional[JSONResponse]:
    """
    Check if a request can be served from the semantic cache.

    Args:
        request: The FastAPI request object

    Returns:
        A JSONResponse if the request can be served from cache, None otherwise
    """
    # Check if semantic cache is enabled via feature gates
    if not is_semantic_cache_enabled():
        logger.debug("Semantic cache is not enabled, skipping cache check")
        return None

    # Get the request body
    body = await request.json()
    logger.info("Checking semantic cache for potential cache hit")

    # Check if semantic cache is initialized
    semantic_cache = GetSemanticCache()
    if semantic_cache:
        # Extract model and messages from the request
        model = body.get("model", "")
        messages = body.get("messages", [])

        # Get the similarity threshold from the request or use the default
        similarity_threshold = body.get("cache_similarity_threshold", None)
        logger.info(
            f"Cache check for model: {model}, custom threshold: {similarity_threshold}"
        )

        # Check if we should skip the cache
        skip_cache = body.get("skip_cache", False)
        if skip_cache:
            logger.info("Skipping cache check due to skip_cache flag")
            return None

        if messages:
            # Log request details
            if messages and len(messages) > 0:
                first_msg = messages[0]
                content = first_msg.get("content", "")
                logger.info(
                    f"Request first message ({first_msg.get('role', 'user')}): {content[:50]}..."
                )

            # Start timing the cache lookup
            cache_start_time = time.time()
            logger.info("Performing semantic cache lookup")

            # Search the cache
            cache_result = semantic_cache.search(
                messages=messages,
                model=model,
                similarity_threshold=similarity_threshold,
            )

            # Record cache lookup latency
            cache_latency = time.time() - cache_start_time
            semantic_cache_latency.labels(server="router").set(cache_latency)
            logger.info(f"Cache lookup took {cache_latency:.4f} seconds")

            if cache_result:
                # Cache hit
                semantic_cache_hits.labels(server="router").inc()
                logger.info(
                    f"CACHE HIT with similarity score: {cache_result['similarity_score']:.4f}"
                )

                # Update hit ratio
                hits = semantic_cache_hits.labels(server="router")._value.get()
                misses = semantic_cache_misses.labels(server="router")._value.get()
                total = hits + misses
                if total > 0:
                    hit_ratio = hits / total
                    semantic_cache_hit_ratio.labels(server="router").set(hit_ratio)
                    logger.info(f"Cache hit ratio: {hit_ratio:.2f} ({hits}/{total})")

                # Construct the response
                response = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {"index": i, "message": response_msg, "finish_reason": "stop"}
                        for i, response_msg in enumerate(
                            cache_result["response_messages"]
                        )
                    ],
                    "usage": cache_result["usage"],
                    "cached": True,
                    "similarity_score": cache_result["similarity_score"],
                }

                # Log response details
                if (
                    cache_result["response_messages"]
                    and len(cache_result["response_messages"]) > 0
                ):
                    first_resp = cache_result["response_messages"][0]
                    content = first_resp.get("content", "")
                    logger.info(f"Cached response: {content[:50]}...")

                logger.info(
                    f"Returning cached response with usage: {cache_result['usage']}"
                )
                return JSONResponse(content=response)
            else:
                # Cache miss
                semantic_cache_misses.labels(server="router").inc()
                logger.info("CACHE MISS - will forward request to backend")

                # Update hit ratio
                hits = semantic_cache_hits.labels(server="router")._value.get()
                misses = semantic_cache_misses.labels(server="router")._value.get()
                total = hits + misses
                if total > 0:
                    hit_ratio = hits / total
                    semantic_cache_hit_ratio.labels(server="router").set(hit_ratio)
                    logger.info(f"Cache hit ratio: {hit_ratio:.2f} ({hits}/{total})")

    # If we get here, either the cache is disabled, there was a cache miss,
    # or the request specified to skip the cache
    return None
