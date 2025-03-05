import logging
import os
import pickle
from typing import Any, Dict, List, Optional

import faiss
import numpy as np

from .base import VectorDBAdapterBase

logger = logging.getLogger(__name__)


class FAISSAdapter(VectorDBAdapterBase):
    """FAISS-based vector database adapter for semantic caching."""

    def __init__(
        self, dim: int = 384, index_file: str = "faiss_index.pkl", cache_dir: str = None
    ):
        """
        Initialize the FAISS adapter.

        Args:
            dim: The dimension of the embedding vectors
            index_file: The filename to use for storing the FAISS index
            cache_dir: The directory to store cache files in (defaults to current directory)
        """
        self.dim = dim

        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
            self.index_file = os.path.join(cache_dir, index_file)
            self.metadata_file = os.path.join(cache_dir, "faiss_metadata.pkl")
        else:
            self.index_file = index_file
            self.metadata_file = "faiss_metadata.pkl"

        if os.path.exists(self.index_file) and os.path.exists(self.metadata_file):
            self.load_index()
        else:
            self.index = faiss.IndexFlatIP(dim)  # Inner product similarity
            self.metadata: List[Dict[str, Any]] = []

        self.save_index()
        logger.info(f"Initialized FAISS adapter with dimension {dim}")

    def load_index(self):
        """Load the FAISS index and metadata from disk."""
        try:
            self.index = faiss.read_index(self.index_file)
            with open(self.metadata_file, "rb") as f:
                self.metadata = pickle.load(f)
            logger.info(f"Loaded FAISS index with {self.index.ntotal} entries")
        except Exception as e:
            logger.error(f"Error loading FAISS index: {str(e)}")
            # Create a new index if loading fails
            self.index = faiss.IndexFlatIP(self.dim)
            self.metadata = []
            self.save_index()

    def save_index(self):
        """Save the FAISS index and metadata to disk."""
        try:
            faiss.write_index(self.index, self.index_file)
            with open(self.metadata_file, "wb") as f:
                pickle.dump(self.metadata, f)
            logger.debug(f"Saved FAISS index with {self.index.ntotal} entries")
        except Exception as e:
            logger.error(f"Error saving FAISS index: {str(e)}")

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
        if self.index.ntotal == 0:
            return None

        embedding = embedding.reshape(1, -1)
        distances, indices = self.index.search(embedding, 1)

        if indices[0][0] != -1 and distances[0][0] >= similarity_threshold:
            metadata = self.metadata[indices[0][0]]
            if metadata["model"] == model:
                return {
                    "response_messages": metadata["response_messages"],
                    "similarity_score": float(distances[0][0]),
                    "usage": metadata["usage"],
                }
        return None

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
        embedding = embedding.reshape(1, -1)
        self.index.add(embedding)

        self.metadata.append(
            {
                "request_messages": request_messages,
                "response_messages": response_messages,
                "model": model,
                "usage": usage,
            }
        )

        self.save_index()
        logger.debug(
            f"Stored new entry in FAISS index, total entries: {self.index.ntotal}"
        )
