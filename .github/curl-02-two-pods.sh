#!/bin/bash

# Send a request to fetch the available models and save the response to a file
result_model=$(curl -s http://"$1":"$2"/v1/models | tee output-02-two-pods/models-02-two-pods.json)

# Check if the response is empty
if [[ -z "$result_model" ]]; then
    echo "Error: Failed to retrieve model list. Response is empty."
    exit 1
fi

# Send a request to generate a text completion and save the response to a file
result_query=$(curl -s -X POST http://"$1":"$2"/v1/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
    | tee output-02-two-pods/query-02-two-pods.json)

# Check if the response is empty
if [[ -z "$result_query" ]]; then
    echo "Error: Failed to retrieve query response. Response is empty."
    exit 1
fi

echo "Requests were successful."
