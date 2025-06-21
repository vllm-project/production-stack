#!/bin/bash
python3 -m vllm_router.app --port "$1" \
    --service-discovery static \
    --static-backends "http://localhost:8100,http://localhost:8200" \
    --static-models "meta-llama/Llama-3.1-8B-Instruct,meta-llama/Llama-3.1-8B-Instruct" \
    --static-model-types "chat,chat" \
    --static-model-labels "llama-prefill,llama-decode" \
    --prefill-model-labels "llama-prefill" \
    --decode-model-labels "llama-decode" \
    --log-stats \
    --log-stats-interval 10 \
    --engine-stats-interval 10 \
    --request-stats-window 10 \
    --request-stats-window 10 \
    --routing-logic disaggregated_prefill
