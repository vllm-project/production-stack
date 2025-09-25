#!/bin/bash

#helm upgrade --install --create-namespace --namespace=ns-vllm test-vllm . -f values-yihua.yaml
helm upgrade --install test-vllm . -f values-additional.yaml #--create-namespace --namespace=vllm
