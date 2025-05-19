#!/bin/bash

IMAGE=lmcache/vllm-openai:2025-05-17-v1
docker run --runtime nvidia --gpus all \
    --env "HF_TOKEN=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" \
    --env "LMCACHE_LOG_LEVEL=DEBUG" \
    --env "LMCACHE_USE_EXPERIMENTAL=True" \
    --env "LMCACHE_ENABLE_NIXL=True" \
    --env "LMCACHE_NIXL_ROLE=sender" \
    --env "LMCACHE_NIXL_RECEIVER_HOST=localhost" \
    --env "LMCACHE_NIXL_RECEIVER_PORT=55555" \
    --env "LMCACHE_NIXL_BUFFER_SIZE=100000000" \
    --env "LMCACHE_NIXL_BUFFER_DEVICE=cuda" \
    --env "LMCACHE_NIXL_ENABLE_GC=True" \
    --env "LMCACHE_LOCAL_CPU=False" \
    --env "LMCACHE_MAX_LOCAL_CPU_SIZE=0" \
    --env "LMCACHE_REMOTE_SERDE=NULL" \
    --env "VLLM_ENABLE_V1_MULTIPROCESSING=1" \
    --env "VLLM_WORKER_MULTIPROC_METHOD=spawn" \
    --env "CUDA_VISIBLE_DEVICES=0" \
    --env "UCX_TLS=cuda_ipc,cuda_copy,tcp" \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    --network host \
    $IMAGE \
     meta-llama/Llama-3.2-1B-Instruct \
    --port 8100 \
    --disable-log-requests \
    --kv-transfer-config \
    '{"kv_connector":"LMCacheConnectorV1","kv_role":"kv_producer","kv_connector_extra_config": {"discard_partial_chunks": false, "lmcache_rpc_port": "receiver"}}'
