#!/bin/bash

# shellcheck disable=SC2034  # result_model appears unused. Verify it or export it.
result_model=$(curl -s http://"$1":"$2"/v1/models | tee output-02-two-pods/models-02-two-pods.json)
# shellcheck disable=SC2034  # result_query appears unused. Verify it or export it.
result_query=$(curl -X POST http://"$1":"$2"/v1/completions -H "Content-Type: application/json" -d '{"model": "facebook/opt-125m", "prompt": "Once upon a time,", "max_tokens": 10}' | tee output-02-two-pods/query-02-two-pods.json)
