#!/bin/bash

set -e

# Deploy the controller
echo "Deploying the StaticRoute controller..."
cd ..
make deploy

# Deploy the example
echo "Deploying the vllm_router and StaticRoute..."
kubectl apply -k examples/

# Wait for the deployment to be ready
echo "Waiting for the vllm_router deployment to be ready..."
kubectl wait --for=condition=available --timeout=60s deployment/vllm-router

# Check the StaticRoute status
echo "Checking the StaticRoute status..."
kubectl get staticroutes staticroute-sample -o yaml

# Check the ConfigMap
echo "Checking the ConfigMap..."
kubectl get configmaps vllm-router-config -o yaml

# Port-forward the vllm_router service
echo "Port-forwarding the vllm_router service..."
echo "Press Ctrl+C to stop the port-forwarding"
kubectl port-forward svc/vllm-router 8000:8000
