"""
Envoy External Processing (extproc) integration for vllm_router.

This module provides the necessary components to run the vllm_router as an
Envoy External Processing service, allowing for semantic cache integration
with Envoy proxies.
"""

from vllm_router.extproc.service import ExtProcService, serve_extproc

__all__ = ["ExtProcService", "serve_extproc"]
