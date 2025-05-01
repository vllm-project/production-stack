# KV Cache Aware Routing Example

This example demonstrates how to set up and run KV cache aware routing with multiple vLLM servers locally without k8s. k8s native support for KV cache aware routing is coming soon.

## Prerequisites

- CUDA-capable GPUs (at least 2 GPUs)
- vLLM installed

## Setup

1. Install the routers and LMCache locally:

```bash
uv pip install -e <path to production stack>
git clone https://github.com/LMCache/LMCache.git
uv pip install LMCache
```

## Running the Example

### 1. Start first vLLM Server

Run the following command to start the first vLLM server on GPU 0:

```bash
LMCACHE_LOG_LEVEL=DEBUG \
LMCACHE_USE_EXPERIMENTAL=True \
LMCACHE_CONFIG_FILE=examples/kvaware_routing/lmcache1.yaml \
CUDA_VISIBLE_DEVICES=0 \
vllm serve mistralai/Mistral-7B-Instruct-v0.2 \
    --no-enable-prefix-caching \
    --port 8000 \
    --kv-transfer-config '{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}'
```

### 2. Start second vLLM Server

Run the following command to start the second vLLM server on GPU 1:

```bash
LMCACHE_LOG_LEVEL=DEBUG \
LMCACHE_USE_EXPERIMENTAL=True \
LMCACHE_CONFIG_FILE=examples/kvaware_routing/lmcache2.yaml \
CUDA_VISIBLE_DEVICES=1 \
vllm serve mistralai/Mistral-7B-Instruct-v0.2 \
    --no-enable-prefix-caching \
    --port 8001 \
    --kv-transfer-config '{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_both"}'
```

### 3. Start the Router

Start the router on port 8005:

```bash
bash run-router.sh 8005
```

### 4. Send Test Requests

Send a request to the router:

```bash
bash send_request.sh 8005
```

### 5. Verify Cache Behavior

Watch the logs on the vLLM server. You should see logs similar to:

```log
[2025-05-01 22:09:02,807] LMCache DEBUG: Sending 1 messages (worker.py:157:lmcache.experimental.cache_controller.worker)
[2025-05-01 22:09:02,811] LMCache DEBUG: Stored 351 out of total 351 tokens (cache_engine.py:256:lmcache.experimental.cache_engine)
[2025-05-01 22:09:02,811] LMCache DEBUG: Sending 1 messages (worker.py:157:lmcache.experimental.cache_controller.worker)
```

### 6. Test Cache Retrieval

Send the same request again:

```bash
bash send_request.sh 8005
```

You should now see cache retrieval logs:

```log
[2025-05-01 22:09:20,704] LMCache INFO: Reqid: cmpl-a76ffbd76f3140ae889f721d137b8412-0, Total tokens 351, LMCache hit tokens: 350, need to load: 350 (vllm_v1_adapter.py:561:lmcache.integration.vllm.vllm_v1_adapter)
[2025-05-01 22:09:20,705] LMCache DEBUG: Scheduled to load 350 tokens for request cmpl-a76ffbd76f3140ae889f721d137b8412-0 (vllm_v1_adapter.py:273:lmcache.integration.vllm.vllm_v1_adapter)
[2025-05-01 22:09:20,716] LMCache DEBUG: Retrieved 351 out of 351 out of total 351 tokens (cache_engine.py:329:lmcache.experimental.cache_engine)
```

## Expected Behavior

- The first request will store the KV cache
- The second request will retrieve the KV cache, demonstrating the cache-aware routing functionality
- The logs will show the number of tokens injected and retrieved from the cache
