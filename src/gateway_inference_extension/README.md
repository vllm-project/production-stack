# Gateway API Inference Extension with agentgateway

This example routes OpenAI-compatible requests to a pool of vLLM model
servers by using agentgateway and the Kubernetes Gateway API Inference
Extension. The llm-d Router provides the Endpoint Picker (EPP) that selects a
model-server pod for each request.

```text
Client -> agentgateway -> HTTPRoute -> InferencePool
                                      -> llm-d Router EPP -> vLLM pod
```

The example pins the following compatible releases:

- Gateway API `v1.6.0`
- Gateway API Inference Extension `v1.5.0`
- agentgateway `v1.4.1`
- llm-d Router `v0.9.0`

Override any version through the corresponding environment variable in
`install.sh`.

## Prerequisites

- A Kubernetes cluster with at least two GPU nodes for the default deployment
- `kubectl` and Helm
- A Hugging Face token with access to
  `meta-llama/Llama-3.2-1B-Instruct`

Create the token secret in the namespace where the model is deployed:

```bash
kubectl create secret generic hf-token \
  --from-literal=token='<YOUR_HF_TOKEN>'
```

## Install

Run the installer from any working directory:

```bash
./src/gateway_inference_extension/install.sh
```

The installer creates the agentgateway control plane, the vLLM deployment, an
agentgateway `Gateway`, and an llm-d Router release. The router chart owns the
`InferencePool`, EPP, RBAC, and `HTTPRoute` resources.

Wait for the vLLM model servers after the model weights download:

```bash
kubectl rollout status deployment/vllm-llama3-1b-instruct \
  --timeout=15m
```

## Send a request

Port-forward the generated Gateway Service:

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

## Verify the routing resources

```bash
kubectl get gateway inference-gateway
kubectl get httproute vllm-llama3-1b-instruct
kubectl get inferencepool vllm-llama3-1b-instruct
kubectl get deployment vllm-llama3-1b-instruct-epp
```

## Uninstall

```bash
./src/gateway_inference_extension/delete.sh
```

Agentgateway, Gateway API, and Inference Extension CRDs are retained because
they are cluster-scoped and might be shared. To remove them from a dedicated
test cluster, explicitly opt in:

```bash
DELETE_SHARED_CRDS=true ./src/gateway_inference_extension/delete.sh
```

## Migration from kgateway

Kgateway's inference-extension operation without agentgateway was deprecated
in kgateway 2.1 and is unsupported in 2.2. This example no longer ships a
kgateway inference configuration.

Existing installations must:

1. Replace the kgateway Helm releases with the agentgateway CRD and controller
   charts.
2. Change `gatewayClassName` from `kgateway` to `agentgateway`.
3. Upgrade the Inference Extension API from
   `inference.networking.x-k8s.io/v1alpha2` to
   `inference.networking.k8s.io/v1`.
4. Replace `targetPortNumber` and `extensionRef` with `targetPorts` and
   `endpointPickerRef`.
5. Replace the locally patched EPP with the llm-d Router Gateway chart.

Generic Gateway API ingress through kgateway is outside the scope of this
deprecation.
