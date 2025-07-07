# Gateway Inference Extension Tutorial

This tutorial guides you through setting up and using the Gateway Inference Extension in a production environment. The extension enables inference capabilities through the gateway, supporting both individual inference models and inference pools.

## Prerequisites

Before starting this tutorial, ensure you have:

- A Kubernetes cluster with GPU nodes available
- `kubectl` configured to access your cluster
- `helm` installed
- A Hugging Face account with API token
- Basic understanding of Kubernetes concepts

## Overview

The Gateway Inference Extension provides:

- **Individual Model Inference**: Direct access to specific models
- **Inference Pools**: Load-balanced access to multiple model instances
- **Gateway API Integration**: Standard Kubernetes Gateway API for routing
- **vLLM Integration**: High-performance inference engine support

## Step 1: Environment Setup

### 1.1 Create Hugging Face Token Secret

First, create a Kubernetes secret with your Hugging Face token:

```bash
# Replace <YOUR_HF_TOKEN> with your actual Hugging Face token
kubectl create secret generic hf-token --from-literal=token=<YOUR_HF_TOKEN>
```

### 1.2 Install Gateway API CRDs

Install the required Custom Resource Definitions (CRDs):

```bash
# Install KGateway CRDs
KGTW_VERSION=v2.0.2
helm upgrade -i --create-namespace --namespace kgateway-system --version $KGTW_VERSION kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds

# Install Gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml

# Install Gateway API inference extension CRDs
VERSION=v0.3.0
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/$VERSION/manifests.yaml
```

### 1.3 Install KGateway with Inference Extension

```bash
# Install KGateway with inference extension enabled
helm upgrade -i --namespace kgateway-system --version $KGTW_VERSION kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set inferenceExtension.enabled=true
```

## Step 2: Deploy vLLM Models

### 2.1 Understanding vLLM Runtime

The vLLM Runtime is a custom resource that manages model deployments. Please check ``configs/vllm/gpu-deployment.yaml`` for an example config.

### 2.2 Apply vLLM Deployment

```bash
# Apply the vLLM deployment configuration
kubectl apply -f configs/vllm/gpu-deployment.yaml
```

**Production Considerations**:

- Adjust resource requests/limits based on your model size and GPU capacity
- Consider using multiple replicas for high availability
- Monitor GPU utilization and adjust accordingly

## Step 3: Configure Inference Resources

### 3.1 Individual Model Configuration

Create an InferenceModel resource for direct model access:

```yaml
apiVersion: inference.networking.x-k8s.io/v1alpha2
kind: InferenceModel
metadata:
  name: legogpt
spec:
  modelName: legogpt
  criticality: Standard
  poolRef:
    name: vllm-llama3-1b-instruct
  targetModels:
  - name: legogpt
    weight: 100
```

### 3.2 Inference Pool Configuration

For routing to multiple model instances, check ``configs/inferencepool-resources.yaml`` for example.

### 3.3 Apply Inference Resources

```bash
# Apply individual model configuration
kubectl apply -f configs/inferencemodel.yaml

# Apply inference pool configuration
kubectl apply -f configs/inferencepool-resources.yaml
```

## Step 4: Configure Gateway Routing

### 4.1 Gateway Configuration

The gateway acts as the entry point for inference requests:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: inference-gateway
spec:
  gatewayClassName: kgateway
  listeners:
  - name: http
    port: 80
    protocol: HTTP
```

### 4.2 HTTPRoute Configuration

HTTPRoute defines how requests are routed to inference resources:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-route
spec:
  parentRefs:
  - group: gateway.networking.k8s.io
    kind: Gateway
    name: inference-gateway
  rules:
  - backendRefs:
    - group: inference.networking.x-k8s.io
      kind: InferencePool
      name: vllm-llama3-1b-instruct
    matches:
    - path:
        type: PathPrefix
        value: /
```

### 4.3 Apply Gateway Resources

```bash
# Apply gateway configuration
kubectl apply -f configs/gateway/kgateway/gateway.yaml

# Apply HTTP route configuration
kubectl apply -f configs/httproute.yaml
```

## Step 5: Testing the Setup

### 5.1 Get Gateway IP Address

```bash
# Get the external IP of the gateway
IP=$(kubectl get gateway/inference-gateway -o jsonpath='{.status.addresses[0].value}')
PORT=80

echo "Gateway IP: $IP"
echo "Gateway Port: $PORT"
```

### 5.2 Send Test Inference Request

```bash
# Test with a simple completion request
curl -i http://${IP}:${PORT}/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "legogpt",
    "prompt": "Write as if you were a critic: San Francisco",
    "max_tokens": 100,
    "temperature": 0.5
  }'
```

### 5.3 Test Chat Completion

```bash
# Test chat completion endpoint
curl -i http://${IP}:${PORT}/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "legogpt",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "max_tokens": 50,
    "temperature": 0.7
  }'
```

## Step 6: Monitoring and Troubleshooting

### 6.1 Check Resource Status

```bash
# Check vLLM runtime status
kubectl get vllmruntime

# Check inference model status
kubectl get inferencemodel

# Check inference pool status
kubectl get inferencepool

# Check gateway status
kubectl get gateway
```

### 6.2 View Logs

```bash
# Get vLLM runtime logs
kubectl logs -l app=vllm-runtime

# Get gateway logs
kubectl logs -n kgateway-system -l app=kgateway
```

## Step 7: Uninstall

To uninstall all the resources installed on the cluster, run the following:

```bash
# Delete the inference extension
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/raw/main/config/manifests/gateway/kgateway/gateway.yaml --ignore-not-found=true
# Delete the inference model and pool resources
kubectl delete -f configs/inferencemodel.yaml --ignore-not-found=true
kubectl delete -f configs/inferencepool-resources.yaml --ignore-not-found=true
# Delete the VLLM deployment
kubectl delete -f configs/vllm/gpu-deployment.yaml --ignore-not-found=true
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v0.3.0/manifests.yaml --ignore-not-found=true
# Delete helm releases
helm uninstall kgateway -n kgateway-system
helm uninstall kgateway-crds -n kgateway-system
# Delete the namespace last to ensure all resources are removed
kubectl delete ns kgateway-system --ignore-not-found=true
```
