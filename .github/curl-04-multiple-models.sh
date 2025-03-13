#!/bin/bash

# Send a request to fetch the available models and save the response to a file
result_model=$(curl -s http://"$1":"$2"/v1/models | tee output-04-multiple-models/models-04-multiple-models.json)

# Initialize Conda environment
# shellcheck disable=SC1091
source /usr/local/bin/conda-init
conda activate llmstack

# Run the Python script to query the model and save the response to a file
result_query=$(python3 tutorials/assets/example-04-openai.py --openai_api_base http://"$1":"$2"/v1/ | tee output-04-multiple-models/query-04-multiple-models.json)

# Check if model response is empty
if [[ -z "$result_model" ]]; then
    echo "Error: Failed to retrieve model list. Response is empty."
    exit 1
fi

# Check if query response is empty
if [[ -z "$result_query" ]]; then
    echo "Error: Failed to retrieve query response. Response is empty."
    exit 1
fi

echo "Requests were successful."
