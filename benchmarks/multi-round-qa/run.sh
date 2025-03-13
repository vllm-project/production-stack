#!/bin/bash

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <model> <base url> <save file key>"
    exit 1
fi

MODEL=$1
BASE_URL=$2

# CONFIGURATION
NUM_USERS=320
NUM_ROUNDS=10

SYSTEM_PROMPT=1000 # Shared system prompt length
CHAT_HISTORY=20000 # User specific chat history length
ANSWER_LEN=100 # Generation length per round

run_benchmark() {
    # $1: qps
    # $2: output file
    python3 ./multi-round-qa.py \
        --num-users $NUM_USERS \
        --num-rounds $NUM_ROUNDS \
        --qps "$1" \
        --shared-system-prompt "$SYSTEM_PROMPT" \
        --user-history-prompt "$CHAT_HISTORY" \
        --answer-len $ANSWER_LEN \
        --model "$MODEL" \
        --base-url "$BASE_URL" \
        --output "$2" \
        --log-interval 30 \
        --time 100
}

KEY=$3

# Run benchmarks for different QPS values
for qps in 4.1 3.9 3.7 3.5 3.1 2.9 2.7 2.5 2.3 2.1 1.9 1.7 1.5 1.3 1.1 0.9 0.7 0.5 0.3 0.1; do
    output_file="${KEY}_output_${qps}.csv"
    run_benchmark "$qps" "$output_file"
done
