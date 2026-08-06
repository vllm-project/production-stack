#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

GATEWAY_API_VERSION=${GATEWAY_API_VERSION:-v1.6.0}
INFERENCE_EXTENSION_VERSION=${INFERENCE_EXTENSION_VERSION:-v1.5.0}
INFERENCE_NAMESPACE=${INFERENCE_NAMESPACE:-default}

if helm status vllm-llama3-1b-instruct \
  --namespace "${INFERENCE_NAMESPACE}" >/dev/null 2>&1; then
  helm uninstall vllm-llama3-1b-instruct \
    --namespace "${INFERENCE_NAMESPACE}"
fi

kubectl delete --namespace "${INFERENCE_NAMESPACE}" \
  -f "${SCRIPT_DIR}/configs/gateway/agentgateway/gateway.yaml" \
  --ignore-not-found=true
kubectl delete --namespace "${INFERENCE_NAMESPACE}" \
  -f "${SCRIPT_DIR}/configs/vllm/gpu-deployment.yaml" \
  --ignore-not-found=true

if helm status agentgateway --namespace agentgateway-system >/dev/null 2>&1; then
  helm uninstall agentgateway --namespace agentgateway-system
fi
# CRDs are cluster-scoped and may be used by other workloads. Delete them only
# when explicitly requested.
if [[ "${DELETE_SHARED_CRDS:-false}" == "true" ]]; then
  if helm status agentgateway-crds --namespace agentgateway-system \
    >/dev/null 2>&1; then
    helm uninstall agentgateway-crds --namespace agentgateway-system
  fi
  kubectl delete -f \
    "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${INFERENCE_EXTENSION_VERSION}/manifests.yaml" \
    --ignore-not-found=true
  kubectl delete -f \
    "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml" \
    --ignore-not-found=true
  kubectl delete namespace agentgateway-system --ignore-not-found=true
fi
