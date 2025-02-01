#!/bin/bash

# Curl and save output
[ ! -d "output" ] && mkdir output
chmod -R 777 output
result_model=$(curl -s http://$1:$2/models | tee output/models.json)

source /usr/local/bin/conda-init
conda activate llmstack
result_query=$(python3 tutorials/assets/example-04-openai.py --openai_api_base "http://$1:$2/" | tee output/query.json)
