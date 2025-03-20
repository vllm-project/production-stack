# Experimental Features for vLLM Router

This directory contains experimental features for the vLLM router. These features are not considered stable and may change or be removed at any time.

## Feature Gates

The vLLM router uses a feature gate mechanism similar to Kubernetes to enable or disable experimental features. Feature gates can be enabled or disabled using the `--feature-gates` command-line argument or the `VLLM_FEATURE_GATES` environment variable.

### Usage

To enable a feature gate, use the following format:

```bash
--feature-gates=FeatureName=true
```

To enable multiple feature gates:

```bash
--feature-gates=FeatureName1=true,FeatureName2=true
```

Or using environment variables:

```bash
export VLLM_FEATURE_GATES=FeatureName=true
```

### Available Feature Gates

| Feature Name | Stage | Default | Description |
|--------------|-------|---------|-------------|
| SemanticCache | Alpha | false | Semantic caching of LLM requests and responses |
| PII | Alpha | false | Detect and block PII in LLM requests |

## Semantic Cache

The semantic cache is an experimental feature that caches LLM responses based on the semantic similarity of requests. This can significantly improve response times for similar requests.

### Configuration

To use the semantic cache, you need to:

1. Enable the feature gate:

   ```bash
   --feature-gates=SemanticCache=true
   ```

2. Configure the semantic cache:

   ```bash
   --semantic-cache-model=all-MiniLM-L6-v2 \
   --semantic-cache-dir=/path/to/cache \
   --semantic-cache-threshold=0.95
   ```

### Parameters

- `--semantic-cache-model`: The sentence transformer model to use for embeddings (default: "all-MiniLM-L6-v2")
- `--semantic-cache-dir`: Directory to store cache files (default: None, in-memory only)
- `--semantic-cache-threshold`: Default similarity threshold for cache hits (0.0-1.0, default: 0.95)

### Client-Side Control

Clients can control caching behavior by adding the following fields to their requests:

- `skip_cache`: Set to `true` to bypass the cache for a specific request
- `cache_similarity_threshold`: Override the default similarity threshold for a specific request

## PII Detection

The PII detection feature is an experimental feature that detects and blocks PII in LLM requests.

### PII Feature Configuration

To enable the PII detection feature, you need to:

1. Enable the feature gate:

   ```bash
   --feature-gates=PII=true
   ```

   This will enable the PII detection feature and use the default analyzer.

2. Configure the PII analyzer:

   ```bash
   --pii-analyzer=[presidio|regex]
   ```

   Available analyzers:
   - `presidio`: Microsoft Presidio-based analyzer (requires additional dependencies)
   - `regex`: Lightweight regex-based analyzer (no additional dependencies)
