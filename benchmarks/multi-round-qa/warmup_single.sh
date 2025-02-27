#!/bin/bash

MODEL=$1
BASE_URL=$2

# CONFIGURATION
NUM_USERS_WARMUP=20

SYSTEM_PROMPT=1000 # Shared system prompt length
CHAT_HISTORY=20000 # User specific chat history length
ANSWER_LEN=100 # Generation length per round

warmup() {
    # Warm up the vLLM with a lot of user queries
    python3 ./multi-round-qa.py \
        --num-users 1 \
        --num-rounds 2 \
        --qps 2 \
        --shared-system-prompt $SYSTEM_PROMPT \
        --user-history-prompt $CHAT_HISTORY \
        --answer-len $ANSWER_LEN \
        --model "$MODEL" \
        --base-url "$BASE_URL" \
        --output /tmp/warmup.csv \
        --log-interval 30 \
        --time $((NUM_USERS_WARMUP / 2))
}

warmup
