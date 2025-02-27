#!/bin/bash

# Ensure correct number of arguments
if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <model> <base url>"
    exit 1
fi

MODEL=$1
BASE_URL=$2

# CONFIGURATION
NUM_USERS=15
NUM_ROUNDS=20

SYSTEM_PROMPT=1000  # Shared system prompt length
CHAT_HISTORY=20000  # User-specific chat history length
ANSWER_LEN=100      # Generation length per round

# Function to run the benchmark
run_benchmark() {
    local qps=$1
    local output_file=$2

    python3 ./multi-round-qa.py \
        --num-users "$NUM_USERS" \
        --num-rounds "$NUM_ROUNDS" \
        --qps "$qps" \
        --shared-system-prompt "$SYSTEM_PROMPT" \
        --user-history-prompt "$CHAT_HISTORY" \
        --answer-len "$ANSWER_LEN" \
        --model "$MODEL" \
        --base-url "$BASE_URL" \
        --output "$output_file" \
        --log-interval 30 \
        --time 100
}

# Validate if a key argument is provided
if [[ -z "$3" ]]; then
    echo "Error: Missing key argument"
    exit 1
fi

key=$3

# Run benchmarks for different QPS values
for qps in 0.3 0.5 0.7 0.9 1.1; do
    output_file="${key}_output_${qps}.csv"
    run_benchmark "$qps" "$output_file"
done
