#!/bin/bash

# Curl and save output
[ ! -d "output" ] && mkdir output
chmod -R 777 output
result_model=$(curl -s http://$1:$2/models | tee output/models.json)
result_query=$(curl -X POST http://$1:$2/completions -H "Content-Type: application/json" -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' | tee output/query.json)
