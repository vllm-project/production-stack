#!/bin/bash

# Curl and save output
[ ! -d "output-04-multiple-models" ] && mkdir output-04-multiple-models
chmod -R 777 output-04-multiple-models
result_model=$(curl -s http://$1:$2/models | tee output-04-multiple-models/models-04-multiple-models.json)

source /usr/local/bin/conda-init
conda activate llmstack
result_query=$(python3 tutorials/assets/example-04-openai.py --openai_api_base "http://$1:$2/" | tee output-04-multiple-models/query-04-multiple-models.json)
