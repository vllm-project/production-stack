from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np


class VectorDBAdapterBase(ABC):
    """Base class for vector database adapters used in semantic caching."""

    @abstractmethod
    def search(
        self, embedding: np.ndarray, model: str, similarity_threshold: float
    ) -> Optional[Dict[str, Any]]:
        """
        Search for a similar embedding in the database.

        Args:
            embedding: The embedding vector to search for
            model: The model name to filter by
            similarity_threshold: The minimum similarity score to consider a match

        Returns:
            A dictionary containing the matched data or None if no match is found
        """
        pass

    @abstractmethod
    def store(
        self,
        embedding: np.ndarray,
        request_messages: List[Dict[str, Any]],
        response_messages: List[Dict[str, Any]],
        model: str,
        usage: Dict[str, Any],
    ):
        """
        Store an embedding and its associated data in the database.

        Args:
            embedding: The embedding vector to store
            request_messages: The messages from the request
            response_messages: The messages from the response
            model: The model name
            usage: The token usage information
        """
        pass
