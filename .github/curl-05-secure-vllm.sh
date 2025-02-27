#!/bin/bash
VLLM_API_KEY=abc123XYZ987

# Curl and save output
[ ! -d "output-05-secure-vllm" ] && mkdir output-05-secure-vllm
chmod -R 777 output-05-secure-vllm
# shellcheck disable=SC2034  # result_model appears unused. Verify it or export it.
# Fetch model list with authentication
curl -s -H "Authorization: Bearer $VLLM_API_KEY" "http://$HOST:$PORT/v1/models" | tee "$OUTPUT_DIR/models-05-secure-vllm.json"

# Run completion query with authentication
curl -s -X POST -H "Authorization: Bearer $VLLM_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
     "http://$HOST:$PORT/v1/completions" | tee "$OUTPUT_DIR/query-05-secure-vllm.json"
