#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

GATEWAY_API_VERSION=${GATEWAY_API_VERSION:-v1.6.0}
INFERENCE_EXTENSION_VERSION=${INFERENCE_EXTENSION_VERSION:-v1.5.0}
AGENTGATEWAY_VERSION=${AGENTGATEWAY_VERSION:-v1.4.1}
LLM_D_ROUTER_VERSION=${LLM_D_ROUTER_VERSION:-v0.9.0}
INFERENCE_NAMESPACE=${INFERENCE_NAMESPACE:-default}

kubectl apply --server-side -f \
  "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"
kubectl apply --server-side -f \
  "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${INFERENCE_EXTENSION_VERSION}/manifests.yaml"

helm upgrade -i --create-namespace \
  --namespace agentgateway-system \
  --version "${AGENTGATEWAY_VERSION}" \
  agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds
helm upgrade -i \
  --namespace agentgateway-system \
  --version "${AGENTGATEWAY_VERSION}" \
  --set inferenceExtension.enabled=true \
  agentgateway oci://cr.agentgateway.dev/charts/agentgateway

kubectl apply --namespace "${INFERENCE_NAMESPACE}" \
  -f "${SCRIPT_DIR}/configs/vllm/gpu-deployment.yaml"
kubectl apply --namespace "${INFERENCE_NAMESPACE}" \
  -f "${SCRIPT_DIR}/configs/gateway/agentgateway/gateway.yaml"

helm upgrade -i vllm-llama3-1b-instruct \
  oci://ghcr.io/llm-d/charts/llm-d-router-gateway \
  --namespace "${INFERENCE_NAMESPACE}" \
  --version "${LLM_D_ROUTER_VERSION}" \
  -f "${SCRIPT_DIR}/configs/llm-d-router-values.yaml"

kubectl wait --namespace "${INFERENCE_NAMESPACE}" \
  --for=condition=Programmed --timeout=120s gateway/inference-gateway
kubectl rollout status --namespace "${INFERENCE_NAMESPACE}" \
  --timeout=120s deployment/vllm-llama3-1b-instruct-epp
kubectl wait --namespace "${INFERENCE_NAMESPACE}" \
  --for=jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'=True \
  --timeout=120s httproute/vllm-llama3-1b-instruct
