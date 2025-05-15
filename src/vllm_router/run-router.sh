#!/bin/bash
if [[ $# -ne 1 ]]; then
    echo "Usage $0 <router port>"
    exit 1
fi

# Use this command when testing with k8s service discovery
# python3 -m vllm_router.app --port "$1" \
#     --service-discovery k8s \
#     --k8s-label-selector release=test \
#     --k8s-namespace default \
#     --routing-logic session \
#     --session-key "x-user-id" \
#     --engine-stats-interval 10 \
#     --log-stats

# Use this command when testing with static service discovery
python3 -m vllm_router.app --port "$1" \
    --service-discovery static \
    --static-backends "http://127.0.0.1:11434,http://127.0.0.1:11434,http://127.0.0.1:11434,http://127.0.0.1:11434" \
    --static-models "qwen3,tinyllama,starcoder2,bge-m3" \
    --static-model-types "chat,chat,completion,embeddings" \
    --static-endpoint-healthcheck-enabled \
    --routing-logic roundrobin

# Use this command when testing with roundrobin routing logic
#python3 router.py --port "$1" \
#    --service-discovery k8s \
#    --k8s-label-selector release=test \
#    --routing-logic roundrobin \
#    --engine-stats-interval 10 \
#    --log-stats
#
