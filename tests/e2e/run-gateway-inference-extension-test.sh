#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../.." && pwd)

GATEWAY_API_VERSION=${GATEWAY_API_VERSION:-v1.6.0}
INFERENCE_EXTENSION_VERSION=${INFERENCE_EXTENSION_VERSION:-v1.5.0}
AGENTGATEWAY_VERSION=${AGENTGATEWAY_VERSION:-v1.4.1}
LLM_D_ROUTER_VERSION=${LLM_D_ROUTER_VERSION:-v0.9.0}
KIND_CLUSTER_NAME=${KIND_CLUSTER_NAME:-vllm-agentgateway-smoke}
port_forward_log="${TMPDIR:-/tmp}/agentgateway-port-forward.log"

for command_name in curl helm kind kubectl; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

if [[ ! "${KIND_CLUSTER_NAME}" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]]; then
  echo "Invalid kind cluster name: ${KIND_CLUSTER_NAME}" >&2
  exit 1
fi

created_cluster=false
port_forward_pid=""

# ShellCheck cannot infer that this function is invoked through the EXIT trap.
# shellcheck disable=SC2317
cleanup() {
  if [[ -n "${port_forward_pid}" ]]; then
    kill "${port_forward_pid}" >/dev/null 2>&1 || true
  fi
  if [[ "${created_cluster}" == "true" ]]; then
    kind delete cluster --name "${KIND_CLUSTER_NAME}"
  fi
}
trap cleanup EXIT

if kind get clusters | grep -Fxq "${KIND_CLUSTER_NAME}"; then
  echo "Refusing to replace existing kind cluster: ${KIND_CLUSTER_NAME}" >&2
  exit 1
fi
kind create cluster --name "${KIND_CLUSTER_NAME}" --wait 120s
created_cluster=true

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

kubectl apply -f \
  "${SCRIPT_DIR}/assets/gateway-inference-extension-simulator.yaml"
kubectl wait --for=condition=Available --timeout=120s \
  deployment/vllm-qwen3-32b

kubectl apply -f \
  "${REPO_ROOT}/src/gateway_inference_extension/configs/gateway/agentgateway/gateway.yaml"
kubectl wait --for=condition=Programmed --timeout=120s \
  gateway/inference-gateway

helm upgrade -i vllm-qwen3-32b \
  oci://ghcr.io/llm-d/charts/llm-d-router-gateway \
  --version "${LLM_D_ROUTER_VERSION}" \
  -f "${REPO_ROOT}/src/gateway_inference_extension/configs/llm-d-router-values.yaml" \
  --set router.modelServers.matchLabels.app=vllm-qwen3-32b

kubectl rollout status --timeout=120s deployment/vllm-qwen3-32b-epp
kubectl wait \
  --for=jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'=True \
  --timeout=120s httproute/vllm-qwen3-32b

kubectl port-forward service/inference-gateway 18080:80 \
  >"${port_forward_log}" 2>&1 &
port_forward_pid=$!

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error \
    http://localhost:18080/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{
      "model": "Qwen/Qwen3-32B",
      "prompt": "Hello from the Production Stack smoke test",
      "max_tokens": 16
    }' >/dev/null; then
    echo "Gateway Inference Extension smoke test passed"
    exit 0
  fi
  if [[ "${attempt}" == "30" ]]; then
    break
  fi
  sleep 2
done

echo "Gateway Inference Extension smoke test failed" >&2
kubectl describe gateway inference-gateway >&2 || true
kubectl describe httproute vllm-qwen3-32b >&2 || true
kubectl logs deployment/vllm-qwen3-32b-epp >&2 || true
kubectl logs deployment/vllm-qwen3-32b >&2 || true
kubectl logs --namespace agentgateway-system deployment/agentgateway >&2 || true
kubectl get events --sort-by=.lastTimestamp >&2 || true
if [[ -f "${port_forward_log}" ]]; then
  echo "=== Port-forward logs ===" >&2
  sed -n '1,240p' "${port_forward_log}" >&2
fi
exit 1
