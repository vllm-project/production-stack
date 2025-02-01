#!/bin/bash

# Curl and save output
[ ! -d "output-01-minimal-example" ] && mkdir output-01-minimal-example
chmod -R 777 output-01-minimal-example
result_model=$(curl -s http://$1:$2/models | tee output-01-minimal-example/models-01-minimal-example.json)
result_query=$(curl -X POST http://$1:$2/completions -H "Content-Type: application/json" -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' | tee output-01-minimal-example/query-01-minimal-example.json)
