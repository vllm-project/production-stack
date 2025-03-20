# Semantic Cache for vLLM Router

This module provides semantic caching functionality for the vLLM router, allowing it to cache LLM responses based on the semantic similarity of requests.

## Overview

The semantic cache uses sentence transformers to generate embeddings for chat messages and stores them in a vector database (FAISS). When a new request comes in, the cache checks if there's a semantically similar request already in the cache. If a match is found, the cached response is returned instead of routing the request to a backend LLM service.

## Features

- Semantic similarity matching using sentence transformers
- Configurable similarity threshold
- Per-request cache control
- Prometheus metrics for cache performance monitoring
- Persistent storage of cache entries

## Installation

In the semantic cache directory, run the following command to install the dependencies:

```bash
pip install -r requirements.txt
```

## Usage

To enable the semantic cache, use the following command-line arguments when starting the vLLM router:

```bash
python -m vllm_router.router --feature-gates=SemanticCache=true [other options]
```

### Command-line Arguments

- `--feature-gates=SemanticCache=true`: Enable semantic caching
- `--semantic-cache-model`: Sentence transformer model to use (default: "all-MiniLM-L6-v2")
- `--semantic-cache-dir`: Directory to store cache files (default: "semantic_cache")
- `--semantic-cache-threshold`: Default similarity threshold for cache hits (default: 0.95)

## Test the semantic cache

```bash
./test_cache.sh
```

## Metrics

The following Prometheus metrics are available:

- `vllm:semantic_cache_hits`: Number of cache hits
- `vllm:semantic_cache_misses`: Number of cache misses
- `vllm:semantic_cache_hit_ratio`: Ratio of cache hits to total requests
- `vllm:semantic_cache_size`: Number of entries in the cache
- `vllm:semantic_cache_latency`: Average latency for cache lookups

## Dependencies

- sentence-transformers
- faiss-cpu
- numpy

## TODO

- Support for streaming responses
- Support for different embedding models for better accuracy
- Support for different vector databases for better performance
- Support for different similarity metrics for better accuracy
