#!/bin/bash
if [[ $# -ne 2 ]]; then
    echo "Usage $0 <router port> <backend url>"
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
# python3 -m vllm_router.app --port "$1" \
#     --service-discovery static \
#     --static-backends "http://localhost:8000" \
#     --static-models "facebook/opt-125m" \
#     --static-model-types "chat" \
#     --log-stats \
#     --log-stats-interval 10 \
#     --engine-stats-interval 10 \
#     --request-stats-window 10 \
#     --request-stats-window 10 \
#     --routing-logic roundrobin

# Use this command when testing with roundrobin routing logic
#python3 router.py --port "$1" \
#    --service-discovery k8s \
#    --k8s-label-selector release=test \
#    --routing-logic roundrobin \
#    --engine-stats-interval 10 \
#    --log-stats
#

# Use this command when testing with whisper transcription
ROUTER_PORT=$1
BACKEND_URL=$2

python3 -m vllm_router.app \
    --host 0.0.0.0 \
    --port "${ROUTER_PORT}" \
    --service-discovery static \
    --static-backends "${BACKEND_URL}" \
    --static-models "openai/whisper-small" \
    --static-model-types "transcription" \
    --routing-logic roundrobin \
    --log-stats \
    --engine-stats-interval 10 \
    --request-stats-window 10
