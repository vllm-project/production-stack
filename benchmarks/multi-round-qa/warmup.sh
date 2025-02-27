#!/bin/bash

# Ensure correct number of arguments
if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <model> <base url>"
    exit 1
fi

MODEL=$1
BASE_URL=$2

# CONFIGURATION
SYSTEM_PROMPT=1000  # Shared system prompt length
CHAT_HISTORY=20000  # User-specific chat history length
ANSWER_LEN=100      # Generation length per round

# Function to warm up the vLLM
warmup() {
    # Calculate warmup time
    local warmup_time=$((NUM_USERS / 2 + 2))

    # Warm up the vLLM with a lot of user queries
    python3 ./multi-round-qa.py \
        --num-users 1 \
        --num-rounds 2 \
        --qps 2 \
        --shared-system-prompt "$SYSTEM_PROMPT" \
        --user-history-prompt "$CHAT_HISTORY" \
        --answer-len "$ANSWER_LEN" \
        --model "$MODEL" \
        --base-url "$BASE_URL" \
        --output /tmp/warmup.csv \
        --log-interval 30 \
        --time "$warmup_time"
}

# Run the warmup function
warmup
