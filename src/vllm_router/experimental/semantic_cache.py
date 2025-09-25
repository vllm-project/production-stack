import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import numpy as np

from vllm_router.experimental.semantic_cache_db import SemanticCacheDB

logger = logging.getLogger("uvicorn")

# Feature gate for semantic cache
_semantic_cache_enabled = False


def is_semantic_cache_enabled() -> bool:
    """
    Check if the semantic cache feature is enabled.

    Returns:
        True if the semantic cache feature is enabled, False otherwise
    """
    return _semantic_cache_enabled


def enable_semantic_cache() -> None:
    """
    Enable the semantic cache feature.
    """
    global _semantic_cache_enabled
    _semantic_cache_enabled = True
    logger.info("Semantic cache feature enabled")


class SemanticCache:
    """
    A semantic cache for LLM requests and responses.
    """

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        cache_dir: Optional[str] = None,
        default_similarity_threshold: float = 0.95,
    ):
        """
        Initialize the semantic cache.

        Args:
            embedding_model: The name of the sentence transformer model to use for embeddings
            cache_dir: The directory to store cache files in
            default_similarity_threshold: The default similarity threshold to use for cache hits
        """
        # Import here to avoid loading sentence-transformers unless needed
        from sentence_transformers import SentenceTransformer

        # Set up the embedding model
        self.embedding_model = SentenceTransformer(embedding_model)
        embedding_dim = self.embedding_model.get_sentence_embedding_dimension()

        # Set up the cache database
        if cache_dir is None:
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "vllm_router")
        self.db = SemanticCacheDB(cache_dir=cache_dir, embedding_dim=embedding_dim)

        # Set the default similarity threshold
        self.default_similarity_threshold = default_similarity_threshold

        # Dictionary to store pending searches and stores
        self.pending_searches = {}
        self.pending_stores = {}

        logger.info(
            f"Initialized SemanticCache with model {embedding_model} "
            f"(dim={embedding_dim}) and threshold {default_similarity_threshold}"
        )
        logger.info(f"Cache directory: {cache_dir}")
        logger.info(f"Current cache size: {self.db.index.ntotal} entries")

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
        logger.debug(f"Generating embedding for text: {text[:100]}...")
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

        # Log the search request
        logger.info(
            f"Searching cache for model: {model} with threshold: {similarity_threshold}"
        )
        logger.info(f"Current cache size: {self.db.index.ntotal} entries")

        # Log the first message content (truncated for readability)
        if messages and len(messages) > 0:
            first_msg = messages[0]
            content = first_msg.get("content", "")
            logger.info(
                f"First message ({first_msg.get('role', 'user')}): {content[:50]}..."
            )
            logger.debug(f"Full messages: {messages}")

        embedding = self.get_embedding(messages)

        result = self.db.search(
            embedding=embedding, model=model, similarity_threshold=similarity_threshold
        )

        if result:
            logger.info(
                f"CACHE HIT for model {model} with similarity score: {result['similarity_score']:.4f}"
            )
            # Log the first response message (truncated for readability)
            if result["response_messages"] and len(result["response_messages"]) > 0:
                first_resp = result["response_messages"][0]
                content = first_resp.get("content", "")
                logger.info(f"Cached response: {content[:50]}...")
                logger.debug(f"Full cached response: {result['response_messages']}")

            logger.info(f"Token usage from cache: {result['usage']}")
            return result

        logger.info(f"CACHE MISS for model {model}")
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
            # Log the store request
            logger.info(f"Storing in cache for model: {model}")

            # Log the first request message (truncated for readability)
            if request_messages and len(request_messages) > 0:
                first_msg = request_messages[0]
                content = first_msg.get("content", "")
                logger.info(
                    f"Request message ({first_msg.get('role', 'user')}): {content[:50]}..."
                )
                logger.debug(f"Full request messages: {request_messages}")

            # Log the first response message (truncated for readability)
            if response_messages and len(response_messages) > 0:
                first_resp = response_messages[0]
                content = first_resp.get("content", "")
                logger.info(f"Response message: {content[:50]}...")
                logger.debug(f"Full response messages: {response_messages}")

            logger.info(f"Token usage to cache: {usage}")

            embedding = self.get_embedding(request_messages)

            self.db.store(
                embedding=embedding,
                request_messages=request_messages,
                response_messages=response_messages,
                model=model,
                usage=usage,
            )
            logger.info(
                f"Successfully stored in cache for model {model}. New cache size: {self.db.index.ntotal} entries"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store in cache: {str(e)}")
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
            return True
        except Exception as e:
            logger.error(f"Failed to complete store operation: {str(e)}")
            return False


# Singleton instance
_semantic_cache_instance = None


def InitializeSemanticCache(
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
        logger.info(f"Initializing semantic cache with model: {embedding_model}")
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
