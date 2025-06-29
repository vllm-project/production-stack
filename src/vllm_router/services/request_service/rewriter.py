# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Request rewriter interface for vLLM router.

This module provides functionality to rewrite requests before they are sent to the backend.
"""

import abc

from vllm_router.log import init_logger
from vllm_router.utils import SingletonABCMeta

logger = init_logger(__name__)


class RequestRewriter(metaclass=SingletonABCMeta):
    """
    Abstract base class for request rewriters.

    Request rewriters can modify the request body before it is sent to the backend.
    This can be used for prompt engineering, model-specific adjustments, or request normalization.
    """

    @abc.abstractmethod
    def rewrite_request(self, request_body: str, model: str, endpoint: str) -> str:
        """
        Rewrite the request body.

        Args:
            request_body: The original request body as string
            model: The model name from the request
            endpoint: The target endpoint of this request

        Returns:
            The rewritten request body as string
        """
        pass


class NoopRequestRewriter(RequestRewriter):
    """
    A request rewriter that does not modify the request.
    """

    def rewrite_request(self, request_body: str, model: str, endpoint: str) -> str:
        """
        Return the request body unchanged.

        Args:
            request_body: The original request body as string
            model: The model name from the request
            endpoint: The target endpoint of this request

        Returns:
            The original request body without any modifications
        """
        return request_body


# Singleton instance
_request_rewriter_instance = None


def initialize_request_rewriter(rewriter_type: str, **kwargs) -> RequestRewriter:
    """
    Initialize the request rewriter singleton.

    Args:
        rewriter_type: The type of rewriter to initialize
        **kwargs: Additional arguments for the rewriter

    Returns:
        The initialized request rewriter instance
    """
    global _request_rewriter_instance

    # TODO: Implement different rewriter types
    # For now, just use the NoopRequestRewriter
    _request_rewriter_instance = NoopRequestRewriter()
    logger.info(f"Initialized placeholder request rewriter (type: {rewriter_type})")

    return _request_rewriter_instance


def is_request_rewriter_initialized() -> bool:
    """
    Check if the request rewriter singleton has been initialized.

    Returns:
        bool: True if the request rewriter has been initialized, False otherwise
    """
    global _request_rewriter_instance
    return _request_rewriter_instance is not None


def get_request_rewriter() -> RequestRewriter:
    """
    Get the request rewriter singleton instance.

    Returns:
        The request rewriter instance or NoopRequestRewriter if not initialized
    """
    global _request_rewriter_instance
    if _request_rewriter_instance is None:
        _request_rewriter_instance = NoopRequestRewriter()
    return _request_rewriter_instance
