#!/bin/bash
set -e

IMAGE_NAME="local/controller:test"

echo "🔄 Undeploying controller..."
make undeploy || true

echo "🔄 Switching to Minikube Docker environment..."
eval $(minikube docker-env)

echo "🔄 Generating CRDs..."
make generate

echo "🔄 Generating manifests..."
make manifests

echo "🐳 Building controller image: $IMAGE_NAME"
make docker-build IMG=$IMAGE_NAME

echo "🚀 Deploying controller to Minikube cluster"
make deploy IMG=$IMAGE_NAME

echo "🔄 Verifying pod status..."
kubectl rollout status deployment/controller-manager -n lora-controller-dev-system || true

echo "📦 Pods in lora-controller-dev-system:"
kubectl get pods -n lora-controller-dev-system

