#!/bin/bash
HOST=$1
PORT=$2
VLLM_API_KEY=abc123XYZ987

# Curl and save output
OUTPUT_DIR="output-05-secure-vllm"
[ ! -d "$OUTPUT_DIR" ] && mkdir $OUTPUT_DIR
chmod -R 777 $OUTPUT_DIR

# Fetch model list with authentication
curl -s -H "Authorization: Bearer $VLLM_API_KEY" "http://$HOST:$PORT/v1/models" | tee "$OUTPUT_DIR/models-05-secure-vllm.json"
# Run completion query with authentication
curl -s -X POST -H "Authorization: Bearer $VLLM_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
     "http://$HOST:$PORT/v1/completions" | tee "$OUTPUT_DIR/query-05-secure-vllm.json"
