#!/bin/bash

# Curl and save output
[ ! -d "output-04-multiple-models" ] && mkdir output-04-multiple-models
chmod -R 777 output-04-multiple-models
# shellcheck disable=SC2034  # result_model appears unused. Verify it or export it.
result_model=$(curl -s "http://$1:$2/models" | tee output-04-multiple-models/models-04-multiple-models.json)

# shellcheck disable=SC1091  # Not following: /usr/local/bin/conda-init was not specified as input
source /usr/local/bin/conda-init
conda activate llmstack

# shellcheck disable=SC2034  # result_query appears unused. Verify it or export it.
result_query=$(python3 tutorials/assets/example-04-openai.py --openai_api_base http://"$1":"$2"/ | tee output-04-multiple-models/query-04-multiple-models.json)
