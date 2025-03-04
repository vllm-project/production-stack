import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from vllm_router.experimental.semantic_cache.db_adapters import (
    FAISSAdapter,
)

logger = logging.getLogger(__name__)


class SemanticCache:
    """
    Semantic cache for LLM requests and responses.

    This class provides functionality to cache LLM responses based on the semantic
    similarity of requests, allowing for efficient reuse of previous responses.
    """

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        cache_dir: str = None,
        default_similarity_threshold: float = 0.95,
    ):
        """
        Initialize the semantic cache.

        Args:
            embedding_model: The name of the sentence transformer model to use for embeddings
            cache_dir: The directory to store cache files in
            default_similarity_threshold: The default similarity threshold to use for cache hits
        """
        self.embedding_model = SentenceTransformer(embedding_model)
        embedding_dim = self.embedding_model.get_sentence_embedding_dimension()

        # Create cache directory if it doesn't exist
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

        # Initialize the vector database
        self.db = FAISSAdapter(dim=embedding_dim, cache_dir=cache_dir)

        # Default similarity threshold
        self.default_similarity_threshold = default_similarity_threshold

        # In-memory storage for pending requests
        self.pending_searches: Dict[str, Dict[str, Any]] = {}
        self.pending_stores: Dict[str, Dict[str, Any]] = {}

        logger.info(
            f"Initialized SemanticCache with model {embedding_model} "
            f"(dim={embedding_dim}) and threshold {default_similarity_threshold}"
        )

    def get_embedding(self, messages: List[Dict[str, str]]) -> np.ndarray:
        """
        Generate an embedding for a list of messages.

        Args:
            messages: A list of message dictionaries with 'role' and 'content' keys

        Returns:
            The embedding vector for the messages
        """
        # Concatenate all message content with role prefixes
        text = " ".join(
            [f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in messages]
        )
        embedding = self.embedding_model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)

    def search(
        self,
        messages: List[Dict[str, str]],
        model: str,
        similarity_threshold: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Search the cache for a similar request.

        Args:
            messages: The messages to search for
            model: The model name to filter by
            similarity_threshold: The minimum similarity score to consider a match
                                 (defaults to self.default_similarity_threshold)

        Returns:
            A dictionary containing the cached response or None if no match is found
        """
        if similarity_threshold is None:
            similarity_threshold = self.default_similarity_threshold

        embedding = self.get_embedding(messages)

        result = self.db.search(
            embedding=embedding, model=model, similarity_threshold=similarity_threshold
        )

        if result:
            logger.info(
                f"Cache hit for model {model} with similarity score: {result['similarity_score']}"
            )
            return result

        logger.info(f"Cache miss for model {model}")
        return None

    def store(
        self,
        request_messages: List[Dict[str, str]],
        response_messages: List[Dict[str, str]],
        model: str,
        usage: Dict[str, int],
    ):
        """
        Store a request-response pair in the cache.

        Args:
            request_messages: The messages from the request
            response_messages: The messages from the response
            model: The model name
            usage: The token usage information
        """
        try:
            embedding = self.get_embedding(request_messages)

            self.db.store(
                embedding=embedding,
                request_messages=request_messages,
                response_messages=response_messages,
                model=model,
                usage=usage,
            )
            logger.debug(
                f"Stored new entry in FAISS index, total entries: {self.db.index.ntotal}"
            )
            logger.info(f"Successfully stored chat for model {model}")

            # Update cache size metric if available
            try:
                from vllm_router.experimental.semantic_cache_integration import (
                    semantic_cache_size,
                )

                semantic_cache_size.labels(server="router").set(self.db.index.ntotal)
                logger.debug(
                    f"Updated cache size metric: {self.db.index.ntotal} entries"
                )
            except ImportError:
                logger.debug(
                    "Could not update cache size metric - integration module not available"
                )

            return True
        except Exception as e:
            logger.error(f"Failed to store chat: {str(e)}")
            return False

    def initiate_search(
        self,
        messages: List[Dict[str, str]],
        model: str,
        similarity_threshold: Optional[float] = None,
    ) -> str:
        """
        Initiate a cache search and return a request ID.

        This is useful for asynchronous processing where the embedding calculation
        can be done in advance of needing the result.

        Args:
            messages: The messages to search for
            model: The model name to filter by
            similarity_threshold: The minimum similarity score to consider a match

        Returns:
            A unique request ID for this search
        """
        if similarity_threshold is None:
            similarity_threshold = self.default_similarity_threshold

        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Calculate and store embedding
        embedding = self.get_embedding(messages)
        self.pending_searches[request_id] = {
            "embedding": embedding,
            "model": model,
            "similarity_threshold": similarity_threshold,
        }

        logger.debug(f"Stored search request with ID: {request_id}")
        return request_id

    def complete_search(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Complete a previously initiated cache search.

        Args:
            request_id: The request ID returned by initiate_search

        Returns:
            A dictionary containing the cached response or None if no match is found
        """
        # Get search data
        search_data = self.pending_searches.pop(request_id, None)
        if not search_data:
            logger.error(f"No pending search found for ID: {request_id}")
            return None

        # Perform search
        result = self.db.search(
            embedding=search_data["embedding"],
            model=search_data["model"],
            similarity_threshold=search_data["similarity_threshold"],
        )

        if result:
            logger.info(
                f"Cache hit with similarity score: {result['similarity_score']}"
            )
            return result

        logger.info("Cache miss")
        return None

    def initiate_store(self, request_messages: List[Dict[str, str]], model: str) -> str:
        """
        Initiate a cache store operation and return a request ID.

        This is useful for asynchronous processing where the embedding calculation
        can be done in advance of having the response.

        Args:
            request_messages: The messages from the request
            model: The model name

        Returns:
            A unique request ID for this store operation
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Calculate and store embedding and request data
        embedding = self.get_embedding(request_messages)
        self.pending_stores[request_id] = {
            "embedding": embedding,
            "request_messages": request_messages,
            "model": model,
        }

        logger.debug(f"Stored store request with ID: {request_id}")
        return request_id

    def complete_store(
        self,
        request_id: str,
        response_messages: List[Dict[str, str]],
        usage: Dict[str, int],
    ) -> bool:
        """
        Complete a previously initiated cache store operation.

        Args:
            request_id: The request ID returned by initiate_store
            response_messages: The messages from the response
            usage: The token usage information

        Returns:
            True if the store operation was successful, False otherwise
        """
        # Get store data
        store_data = self.pending_stores.pop(request_id, None)
        if not store_data:
            logger.error(f"No pending store found for ID: {request_id}")
            return False

        try:
            # Store in database
            self.db.store(
                embedding=store_data["embedding"],
                request_messages=store_data["request_messages"],
                response_messages=response_messages,
                model=store_data["model"],
                usage=usage,
            )
            logger.info(f"Successfully stored chat for model {store_data['model']}")

            # Update cache size metric if available
            try:
                from vllm_router.experimental.semantic_cache_integration import (
                    semantic_cache_size,
                )

                semantic_cache_size.labels(server="router").set(self.db.index.ntotal)
                logger.debug(
                    f"Updated cache size metric: {self.db.index.ntotal} entries"
                )
            except ImportError:
                logger.debug(
                    "Could not update cache size metric - integration module not available"
                )

            return True
        except Exception as e:
            logger.error(f"Failed to store chat: {str(e)}")
            return False


# Singleton instance
_semantic_cache_instance = None


def initialize_semantic_cache(
    embedding_model: str = "all-MiniLM-L6-v2",
    cache_dir: str = None,
    default_similarity_threshold: float = 0.95,
) -> SemanticCache:
    """
    Initialize the semantic cache singleton.

    Args:
        embedding_model: The name of the sentence transformer model to use for embeddings
        cache_dir: The directory to store cache files in
        default_similarity_threshold: The default similarity threshold to use for cache hits

    Returns:
        The initialized semantic cache instance
    """
    global _semantic_cache_instance
    if _semantic_cache_instance is None:
        _semantic_cache_instance = SemanticCache(
            embedding_model=embedding_model,
            cache_dir=cache_dir,
            default_similarity_threshold=default_similarity_threshold,
        )
    return _semantic_cache_instance


def GetSemanticCache() -> Optional[SemanticCache]:
    """
    Get the semantic cache singleton instance.

    Returns:
        The semantic cache instance or None if it hasn't been initialized
    """
    return _semantic_cache_instance
