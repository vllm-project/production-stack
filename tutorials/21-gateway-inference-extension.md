# Gateway API Inference Extension with agentgateway

This tutorial deploys agentgateway as an inference gateway for a pool of vLLM
model servers. The Kubernetes Gateway API Inference Extension defines the
`InferencePool` contract, and the llm-d Router Endpoint Picker (EPP) selects a
model-server pod for each request.

```text
Client -> agentgateway -> HTTPRoute -> InferencePool
                                      -> llm-d Router EPP -> vLLM pod
```

## Prerequisites

- A Kubernetes cluster with at least two GPU nodes
- `kubectl` configured for the cluster
- Helm 3
- A Hugging Face token with access to
  `meta-llama/Llama-3.2-1B-Instruct`

The example pins Gateway API `v1.6.0`, Inference Extension `v1.5.0`,
agentgateway `v1.4.1`, and llm-d Router `v0.9.0`.

## Step 1: Create the model credential

```bash
kubectl create secret generic hf-token \
  --from-literal=token='<YOUR_HF_TOKEN>'
```

## Step 2: Install the APIs and agentgateway

```bash
export GATEWAY_API_VERSION=v1.6.0
export INFERENCE_EXTENSION_VERSION=v1.5.0
export AGENTGATEWAY_VERSION=v1.4.1

kubectl apply --server-side -f \
  "https://github.com/kubernetes-sigs/gateway-api/releases/download/${GATEWAY_API_VERSION}/standard-install.yaml"

kubectl apply -f \
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
```

## Step 3: Deploy vLLM

The example deployment runs two replicas of
`meta-llama/Llama-3.2-1B-Instruct` and labels each pod with
`app: vllm-llama3-1b-instruct`. The InferencePool uses that label to discover
model servers.

```bash
kubectl apply -f \
  src/gateway_inference_extension/configs/vllm/gpu-deployment.yaml

kubectl rollout status deployment/vllm-llama3-1b-instruct \
  --timeout=15m
```

Adjust GPU resources, replica count, and model-server arguments before using
the example in production.

## Step 4: Create the agentgateway Gateway

```bash
kubectl apply -f \
  src/gateway_inference_extension/configs/gateway/agentgateway/gateway.yaml

kubectl wait --for=condition=Programmed --timeout=120s \
  gateway/inference-gateway
```

The Gateway uses the agentgateway GatewayClass:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: inference-gateway
spec:
  gatewayClassName: agentgateway
  listeners:
    - name: http
      port: 80
      protocol: HTTP
```

## Step 5: Install the llm-d Router

The llm-d Router Gateway chart creates the current
`inference.networking.k8s.io/v1` InferencePool, the EPP Deployment and Service,
RBAC, and an HTTPRoute attached to `inference-gateway`.

```bash
export LLM_D_ROUTER_VERSION=v0.9.0

helm upgrade -i vllm-llama3-1b-instruct \
  oci://ghcr.io/llm-d/charts/llm-d-router-gateway \
  --version "${LLM_D_ROUTER_VERSION}" \
  -f src/gateway_inference_extension/configs/llm-d-router-values.yaml

kubectl rollout status deployment/vllm-llama3-1b-instruct-epp \
  --timeout=120s
```

The values set `provider.name=none` because agentgateway processes the
chart-created HTTPRoute and InferencePool directly. They also select the vLLM
pods through `router.modelServers.matchLabels`.

## Step 6: Verify the resources

```bash
kubectl get gateway inference-gateway
kubectl get httproute vllm-llama3-1b-instruct
kubectl get inferencepool vllm-llama3-1b-instruct
kubectl get deployment vllm-llama3-1b-instruct-epp
```

Check the Gateway and route conditions if traffic is not flowing:

```bash
kubectl describe gateway inference-gateway
kubectl describe httproute vllm-llama3-1b-instruct
kubectl logs deployment/vllm-llama3-1b-instruct-epp
kubectl logs -n agentgateway-system deployment/agentgateway
```

## Step 7: Send a request

```bash
kubectl port-forward service/inference-gateway 8080:80
```

In a separate terminal:

```bash
curl -i http://localhost:8080/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "meta-llama/Llama-3.2-1B-Instruct",
    "prompt": "Write as if you were a critic: San Francisco",
    "max_tokens": 100,
    "temperature": 0.5
  }'
```

## Optional: Use agentgateway AI policies

The default route points directly to the InferencePool. This is appropriate
when only endpoint selection is needed. To use agentgateway features such as
token-based rate limiting, guardrails, transformations, and LLM observability,
route to an `AgentgatewayBackend` whose custom provider references the
InferencePool. See the
[agentgateway inference routing guide](https://agentgateway.dev/docs/kubernetes/latest/llm/inference/inference-routing/).

## Uninstall

```bash
./src/gateway_inference_extension/delete.sh
```

The cleanup script retains shared agentgateway, Gateway API, and Inference
Extension CRDs. On a dedicated test cluster, remove them explicitly with:

```bash
DELETE_SHARED_CRDS=true ./src/gateway_inference_extension/delete.sh
```

## Migrating from kgateway

Kgateway's inference-extension operation without agentgateway was deprecated
in kgateway 2.1 and is unsupported in 2.2. The Production Stack inference
example no longer includes a kgateway configuration or a locally patched EPP.

For an existing deployment:

1. Install agentgateway and change `gatewayClassName` from `kgateway` to
   `agentgateway`.
2. Upgrade `InferencePool` from
   `inference.networking.x-k8s.io/v1alpha2` to
   `inference.networking.k8s.io/v1`.
3. Replace `targetPortNumber` with `targetPorts` and `extensionRef` with
   `endpointPickerRef`.
4. Remove obsolete `InferenceModel` resources.
5. Replace the custom EPP Deployment, Service, and RBAC with the llm-d Router
   Gateway chart.
6. Remove the kgateway releases only after the agentgateway route reports
   `Accepted=True` and an inference request succeeds.

This deprecation does not apply to kgateway used as a generic Gateway API
ingress controller.
