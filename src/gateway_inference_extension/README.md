# Gateway Inference Extension

This extension enables inference capabilities through the gateway, supporting both individual inference models and inference pools.

## Deployment Configuration

### 1. Create Custom Configuration

Create your own deployment configuration in the `configs/` folder. Checkout the examples in the folder.

First, set your Huggingface token by:

```bash
kubectl create secret generic hf-token --from-literal=token=<YOUR HF_TOKEN>
```

Then install all the resources and vLLM deployments by:

```bash
# Install KGateway CRDs first
KGTW_VERSION=v2.0.2
helm upgrade -i --create-namespace --namespace kgateway-system --version $KGTW_VERSION kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds
# Install gateway API CRDs
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.3.0/standard-install.yaml

# Install Gateway API inference extension CRDs
VERSION=v0.3.0
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/$VERSION/manifests.yaml

# Install KGateway with inference extension enabled
helm upgrade -i --namespace kgateway-system --version $KGTW_VERSION kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway --set inferenceExtension.enabled=true

# Apply VLLM deployment using the VLLMRuntime CRD
kubectl apply -f configs/vllm/vllm-runtime.yaml

# Apply inference model and pool resources
kubectl apply -f configs/inferencemodel.yaml
kubectl apply -f configs/inferencepool-resources.yaml

# Apply Gateway and HTTPRoute resources
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/raw/main/config/manifests/gateway/kgateway/gateway.yaml
kubectl apply -f configs/httproute.yaml
```

## Usage

### 1. Get Gateway IP

```bash
IP=$(kubectl get gateway/inference-gateway -o jsonpath='{.status.addresses[0].value}')
```

### 2. Send Inference Request

```bash
curl -i http://${IP}:${PORT}/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "legogpt",
    "prompt": "Write as if you were a critic: San Francisco",
    "max_tokens": 100,
    "temperature": 0.5
  }'
```

## Notes

- Ensure your model is properly configured and deployed before sending requests
- Monitor resource usage and adjust configurations as needed
- For production deployments, consider implementing proper authentication and rate limiting
