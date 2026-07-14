# GPU and Cache Aware Inference Controller Design

## Overview

The Inference Controller is a Kubernetes operator that manages the routing and orchestration of vLLM inference services. It provides a declarative way to manage model serving, caching, and routing in a Kubernetes environment.

## Use Cases

1. **Model Serving Orchestration**
   - Deploy and manage vLLM inference services
   - Configure tensor parallelism for distributed model serving

2. **Caching Layer Management**
   - Deploy and manage KV cache, attention cache, and hybrid cache services
   - Configure cache size, TTL, and transfer policies
   - Monitor cache performance and statistics

3. **Intelligent Request Routing**
   - Route requests to appropriate model instances using routing rules
   - Implement session affinity for consistent model access

4. **Performance Optimization**
   - Enable speculative decoding for faster inference
   - Support prefill-decoding disaggregation
   - Implement efficient cache transfer policies

## Custom Resource Definitions (CRDs)

### InferenceGateway

The `InferenceGateway` CRD manages the routing layer for model inference requests with GPU-aware and cache-efficient routing.

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: InferenceGateway
metadata:
  name: llm-gateway
spec:
  schedulingPolicy: "gpu-load-aware"       # Use GPU metrics for routing
  routeStrategy: "PrefixHash"              # Enable prefix-based routing for cache affinity
  sessionAffinity: true                    # Ensure multi-turn sessions are pinned
  routes:
    - model: "llama3-70b"
      inferenceServiceRef: "llama3-chatbot-service"
    - model: "mistral3"
      inferenceServiceRef: "mistral-agent-service"
```

### InferenceService

The `InferenceService` CRD manages individual model serving instances with integrated caching and NLP filtering.

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: InferenceService
metadata:
  name: llama3-chatbot-service
spec:
  modelName: "llama3-70b"
  backendRef: "chatbot-service-backend"
  inferenceCacheRef: "llama3-chatbot-cache"
  nlpFilters:
    semanticCache:
      storeRef: "redis-nlp-cache"
      threshold: 0.85
      ttlSeconds: 3600
    promptGuard:
      blockedPatterns:
        - "Name"
        - "SSN"
```

### InferenceCache

The `InferenceCache` CRD manages GPU KV caching with support for PDD and speculative decoding.

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: InferenceCache
metadata:
  name: llama3-chatbot-cache
spec:
  modelName: "llama3-70b"
  kvCacheTransferPolicy:
    thresholdHitRate: 0.8
    evictionThreshold: 0.9
  pddRef: "pdd-llama3-chatbot"
  sdRef: "sd-llama3-chatbot"
```

### SpeculativeDecoding

The `SpeculativeDecoding` CRD manages speculative decoding configuration.

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: SpeculativeDecoding
metadata:
  name: sd-llama3-chatbot
spec:
  draftModel: "llama3-1b"
  targetModel: "llama3-70b"
```

### PrefillDecodingDisaggregation

The `PrefillDecodingDisaggregation` CRD manages PDD configuration and topology.

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: PrefillDecodingDisaggregation
metadata:
  name: pdd-llama3-chatbot
spec:
  modelName: "llama3-70b"
  topologyHint:
    nodeSelector:
      gpuType: "NVIDIA-A100"
      zone: "rack1"
status:
  prefillPod: "llama3-chatbot-prefill-0"
  decodeTargetPod: "llama3-chatbot-decode-1"
```

## Controller Flow

### InferenceGateway Controller

```mermaid
graph TD
    A[Watch InferenceGateway] --> B{Resource Exists?}
    B -->|No| C[Return]
    B -->|Yes| D[Get InferenceServices]
    D --> E[Setup GPU Metrics Collection]
    E --> F[Configure Route Strategy]
    F --> G[Setup Session Affinity]
    G --> H[Update Status]
```

### InferenceService Controller

```mermaid
graph TD
    A[Watch InferenceService] --> B{Resource Exists?}
    B -->|No| C[Return]
    B -->|Yes| D[Setup Backend]
    D --> E[Configure Cache]
    E --> F[Setup NLP Filters]
    F --> G[Update Status]
```

### InferenceCache Controller

```mermaid
graph TD
    A[Watch InferenceCache] --> B{Resource Exists?}
    B -->|No| C[Return]
    B -->|Yes| D[Setup KV Cache]
    D --> E[Configure PDD]
    E --> F[Setup Speculative Decoding]
    F --> G[Update Status]
```

## Resource Relationships

```mermaid
graph LR
    Gateway[InferenceGateway] --> Service[InferenceService]
    Service --> Cache[InferenceCache]
    Cache --> PDD[PDD]
    Cache --> SD[Speculative Decoding]
```

## Deployment Architecture

```mermaid
graph TD
    Client[Client] --> Gateway[InferenceGateway]
    Gateway --> Service1[InferenceService 1]
    Gateway --> Service2[InferenceService 2]
    Service1 --> Cache1[InferenceCache 1]
    Service2 --> Cache2[InferenceCache 2]
    Cache1 --> PDD1[PDD Service]
    Cache1 --> SD1[Speculative Decoding]
    Cache2 --> PDD2[PDD Service]
    Cache2 --> SD2[Speculative Decoding]
```
