#!/bin/bash

HOST=$1
PORT=$2

# Fetch the model list
result_model=$(curl -s "http://$HOST:$PORT/v1/models" | tee "output-06-monitoring/models.json")
if [[ -z "$result_model" ]]; then
    echo "Error: Model list request failed or returned an empty response."
    exit 1
fi

# Send a request to generate a text completion and save the response to a file
result_query=$(curl -s -X POST http://"$1":"$2"/v1/completions \
    -H "Content-Type: application/json" \
    -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' \
    | tee output-06-monitoring/query-06-monitoring.json)

# Check if the response is empty
if [[ -z "$result_query" ]]; then
    echo "Error: Failed to retrieve query response. Response is empty."
    exit 1
fi

echo "Requests were successful."

# TODO: add prometheus query to validate metrics collection
