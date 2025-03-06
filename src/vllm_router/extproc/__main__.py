"""
Entrypoint for the vllm_router extproc service.
"""

import logging
import sys

from vllm_router.extproc import ExtProcService, serve_extproc
from vllm_router.parsers.parser import parse_args
from vllm_router.experimental.semantic_cache import (
    enable_semantic_cache,
    initialize_semantic_cache,
    is_semantic_cache_enabled,
)

try:
    from envoy_data_plane.envoy.service.ext_proc.v3 import ProcessingRequest
    extproc_available = True
except ImportError:
    extproc_available = False


def main():
    """
    Main entry point for the extproc service.
    """
    # Use the existing parser from parsers directory
    args = parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    logger = logging.getLogger("vllm_router.extproc")
    
    # Check if extproc is available
    if not extproc_available:
        logger.error("Envoy extproc protobuf definitions not available. Please install the required dependencies.")
        logger.error("You can generate the protobuf code using protoc or install a pre-built package.")
        sys.exit(1)
    
    # Enable semantic cache
    enable_semantic_cache()
    
    if not is_semantic_cache_enabled():
        logger.error("Failed to enable semantic cache. The extproc service requires semantic cache to be enabled.")
        sys.exit(1)
    
    # Initialize semantic cache
    semantic_cache_model = getattr(args, "semantic_cache_model", "all-MiniLM-L6-v2")
    semantic_cache_dir = getattr(args, "semantic_cache_dir", "semantic_cache")
    semantic_cache_threshold = getattr(args, "semantic_cache_threshold", 0.95)
    
    logger.info(f"Initializing semantic cache with model: {semantic_cache_model}")
    logger.info(f"Semantic cache directory: {semantic_cache_dir}")
    logger.info(f"Semantic cache threshold: {semantic_cache_threshold}")
    
    cache = initialize_semantic_cache(
        embedding_model=semantic_cache_model,
        cache_dir=semantic_cache_dir,
        default_similarity_threshold=semantic_cache_threshold,
    )
    
    if not cache:
        logger.error("Failed to initialize semantic cache. The extproc service will not use semantic cache.")
    
    # Create and start the service
    service = ExtProcService()
    extproc_port = getattr(args, "extproc_port", 50051)
    extproc_grace_period = getattr(args, "extproc_grace_period", 5)
    
    logger.info(f"Starting extproc service on port {extproc_port}...")
    serve_extproc(service, extproc_port, extproc_grace_period)


if __name__ == "__main__":
    main() 