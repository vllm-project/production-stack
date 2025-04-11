#!/bin/bash

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 <model> <base url> <save file key>"
    exit 1
fi



MODEL=$1
BASE_URL=$2

# CONFIGURATION
NUM_USERS=120
NUM_ROUNDS=2

SYSTEM_PROMPT=0 # Shared system prompt length
CHAT_HISTORY=500 # User specific chat history length
ANSWER_LEN=50 # Generation length per round

run_benchmark() {
    # $1: qps
    # $2: output file

    # Real run
    python3 ./multi-round-qa-pd.py \
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
        --time 60

    sleep 10
}

KEY=$3

QPS_VALUES=(1.1)

# Run benchmarks for the determined QPS values
for qps in "${QPS_VALUES[@]}"; do
    output_file="${KEY}_output_${qps}.csv"
    run_benchmark "$qps" "$output_file"
done
