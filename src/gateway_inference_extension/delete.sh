#!/bin/bash

# Delete the inference extension
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/raw/main/config/manifests/gateway/kgateway/gateway.yaml

# Delete the inference model and pool resources
kubectl delete -f configs/inferencemodel.yaml
kubectl delete -f configs/inferencepool-resources.yaml

# Delete the VLLM deployment
kubectl delete -f configs/vllm/gpu-deployment.yaml

kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v0.3.0/manifests.yaml

helm uninstall kgateway -n kgateway-system
helm uninstall kgateway-crds -n kgateway-system
kubectl delete ns kgateway-system
