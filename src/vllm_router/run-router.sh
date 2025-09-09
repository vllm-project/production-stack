#!/bin/bash
if [[ $# -lt 1 ]]; then
    echo "Usage $0 <router port> [workers]"
    echo "  router port: The port to run the router on"
    echo "  workers: (optional) Number of worker processes (default: 1)"
    exit 1
fi

PORT=$1
WORKERS=${2:-1}

# Use this command when testing with k8s service discovery
# python3 -m vllm_router.app --port "$PORT" --workers "$WORKERS" \
#     --service-discovery k8s \
#     --k8s-label-selector release=test \
#     --k8s-namespace default \
#     --routing-logic session \
#     --session-key "x-user-id" \
#     --engine-stats-interval 10 \
#     --log-stats

# Use this command when testing with static service discovery
python3 -m vllm_router.app --port "$PORT" --workers "$WORKERS" \
    --service-discovery static \
    --static-backends "http://localhost:8000" \
    --static-models "facebook/opt-125m" \
    --static-model-types "chat" \
    --log-stats \
    --log-stats-interval 10 \
    --engine-stats-interval 10 \
    --request-stats-window 10 \
    --request-stats-window 10 \
    --routing-logic roundrobin

# Use this command when testing with roundrobin routing logic
#python3 -m vllm_router.app --port "$PORT" --workers "$WORKERS" \
#    --service-discovery k8s \
#    --k8s-label-selector release=test \
#    --routing-logic roundrobin \
#    --engine-stats-interval 10 \
#    --log-stats
#
