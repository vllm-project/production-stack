#!/bin/bash

# Retrieve host and port from script arguments
HOST=$1
PORT=$2
VLLM_API_KEY=abc123XYZ987  # API key for authentication

# Directory to store output
OUTPUT_DIR="output-05-secure-vllm"
[ ! -d "$OUTPUT_DIR" ] && mkdir "$OUTPUT_DIR"  # Create directory if it doesn't exist
chmod -R 777 "$OUTPUT_DIR"  # Ensure full read/write permissions

# Fetch the model list with authentication and save the response to a file
curl -s -H "Authorization: Bearer $VLLM_API_KEY" \
     "http://$HOST:$PORT/v1/models" | tee "$OUTPUT_DIR/models-05-secure-vllm.json"

# Run the text completion query with authentication and save the response to a file
curl -s -X POST -H "Authorization: Bearer $VLLM_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
     "http://$HOST:$PORT/v1/completions" | tee "$OUTPUT_DIR/query-05-secure-vllm.json"

# Validate model response
if [[ ! -s "$OUTPUT_DIR/models-05-secure-vllm.json" ]]; then
    echo "Error: Model list request failed or returned an empty response."
    exit 1
fi

# Validate query response
if [[ ! -s "$OUTPUT_DIR/query-05-secure-vllm.json" ]]; then
    echo "Error: Completion request failed or returned an empty response."
    exit 1
fi

echo "Requests completed successfully."
