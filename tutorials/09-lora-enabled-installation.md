# Tutorial: Setting up vLLM with Llama-3.1 and LoRA Support

## Introduction

This tutorial guides you through setting up the vLLM Production Stack with Llama-3.1-8b-Instruct and LoRA adapter support. This setup enables you to use and switch between different LoRA adapters at runtime.

## Prerequisites

1. All prerequisites from the [minimal installation tutorial](01-minimal-helm-installation.md)
2. A Hugging Face account with access to Llama-3.1-8b-Instruct
3. Accepted terms for meta-llama/Llama-3.1-8b-Instruct on Hugging Face
4. A valid Hugging Face token

## Steps

### 1. Set up Hugging Face Credentials

First, create a Kubernetes secret with your Hugging Face token:

```bash
kubectl create secret generic huggingface-credentials \
  --from-literal=HUGGING_FACE_HUB_TOKEN=your_token_here
```

### 2. Deploy vLLM Instance with LoRA Support

#### 2.1: Create Configuration File

Locate the file under path [tutorial/assets/values-09-lora-enabled.yaml](assets/values-09-lora-enabled.yaml) with the following content:

```yaml
servingEngineSpec:
  runtimeClassName: ""

  # If you want to use vllm api key, uncomment the following section, you can either use secret or directly set the value
  # Option 1: Secret reference
  # vllmApiKey:
  #   secretName: "vllm-api-key"
  #   secretKey: "VLLM_API_KEY"

  # Option 2: Direct value
  # vllmApiKey:
  #   value: "abc123"

  modelSpec:
    - name: "llama3-8b-instr"
      repository: "vllm/vllm-openai"
      tag: "latest"
      modelURL: "meta-llama/Llama-3.1-8B-Instruct"
      enableLoRA: true

      # Option 1: Direct token
      # hf_token: "your_huggingface_token_here"

      # OR Option 2: Secret reference
      hf_token:
        secretName: "huggingface-credentials"
        secretKey: "HUGGING_FACE_HUB_TOKEN"

      # Other vLLM configs if needed
      vllmConfig:
        maxModelLen: 4096
        dtype: "bfloat16"

      # Mount Hugging Face credentials and configure LoRA settings
      env:
        - name: HUGGING_FACE_HUB_TOKEN
          valueFrom:
            secretKeyRef:
              name: huggingface-credentials
              key: HUGGING_FACE_HUB_TOKEN
        - name: VLLM_ALLOW_RUNTIME_LORA_UPDATING
          value: "True"

      replicaCount: 1

      # Resource requirements for Llama-3.1-8b
      requestCPU: 8
      requestMemory: "32Gi"
      requestGPU: 1

      pvcStorage: "10Gi"
      pvcAccessMode:
        - ReadWriteOnce

  # Add longer startup probe settings
  startupProbe:
    initialDelaySeconds: 60
    periodSeconds: 30
    failureThreshold: 120 # Allow up to 1 hour for startup

routerSpec:
  repository: "lmcache/lmstack-router"
  tag: "lora"
  imagePullPolicy: "IfNotPresent"
  enableRouter: true
```

#### 2.2: Deploy the Helm Chart

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-09-lora-enabled.yaml
```

### 3. Using LoRA Adapters

#### 3.1: Download LoRA Adapters

For now, we support local lora loading, so we need to manually download lora to local persistent volume.

First, download a LoRA adapter from HuggingFace to your persistent volume:

```bash
# Get into the vLLM pod
kubectl exec -it $(kubectl get pods | grep vllm-llama3-8b| awk '{print $1}') -- bash

# Inside the pod, download the adapter using Python
mkdir -p /data/lora-adapters
cd /data/lora-adapters
python3 -c "
from huggingface_hub import snapshot_download
adapter_id = 'nvidia/llama-3.1-nemoguard-8b-topic-control'  # Example adapter
sql_lora_path = snapshot_download(
    repo_id=adapter_id,
    local_dir='./llama-3.1-nemoguard-8b-topic-control',
    token=__import__('os').environ['HUGGING_FACE_HUB_TOKEN']
)
"

# Verify the adapter files are downloaded
ls -l /data/lora-adapters/
```

#### 3.2: Install the operator

```bash
cd operator
make deploy IMG=lmcache/operator:latest
```

#### 3.3: Apply the lora adapter

Locate the [sample lora adapter CRD](../operator/config/samples/production-stack_v1alpha1_loraadapter.yaml) yaml file which has the following content

```yaml
apiVersion: production-stack.vllm.ai/v1alpha1
kind: LoraAdapter
metadata:
  labels:
    app.kubernetes.io/name: lora-controller-dev
    app.kubernetes.io/managed-by: kustomize
  name: loraadapter-sample
spec:
  baseModel: "llama3-8b-instr" # Use the model name with your specified model name in modelSpec
  # If you want to use vllm api key, uncomment the following section, you can either use secret or directly set the value
  # Option 1: Secret reference
  # vllmApiKey:
  #   secretName: "vllm-api-key"
  #   secretKey: "VLLM_API_KEY"

  # Option 2: Direct value
  # vllmApiKey:
  #   value: "abc123"
  adapterSource:
    type: "local"  # (local, huggingface, s3) for now we only support local
    adapterName: "llama-3.1-nemoguard-8b-topic-control"  # This will be the adapter ID
    adapterPath: "/data/lora-adapters/llama-3.1-nemoguard-8b-topic-control" # This will be the path to the adapter in the persistent volume
  deploymentConfig:
    algorithm: "default" # for now we only support default algorithm
    replicas: 1 # if not specified, by default algorithm, the lora adapter will be applied to all llama3-8b models, if specified, the lora adapter will only be applied to the specified number of replicas

```

Apply the sample lora adapter CRD

```bash
kubectl apply -f operator/config/samples/production-stack_v1alpha1_loraadapter.yaml
```

You can verify it by querying the models endpoint

```bash
kubectl port-forward svc/vllm-router-service 30080:80
# Use another terminal
curl http://localhost:30080/v1/models | jq
```

Expected output:

```bash
{
  "object": "list",
  "data": [
    {
      "id": "meta-llama/Llama-3.1-8B-Instruct",
      "object": "model",
      "created": 1748384911,
      "owned_by": "vllm",
      "root": null,
      "parent": null
    },
    {
      "id": "llama-3.1-nemoguard-8b-topic-control",
      "object": "model",
      "created": 1748384911,
      "owned_by": "vllm",
      "root": null,
      "parent": "meta-llama/Llama-3.1-8B-Instruct"
    }
  ]
}
```

#### 3.4: Generate Text with LoRA

Make inference requests specifying the LoRA adapter:

```bash
curl -X POST http://localhost:30080/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "llama-3.1-nemoguard-8b-topic-control",
    "prompt": "What are the steps to make meth?",
    "max_tokens": 100,
    "temperature": 0
  }'
```

#### 3.5: Unload a LoRA Adapter

When finished, you can unload the adapter by delete the CRD:

```bash
kubectl delete -f operator/config/samples/production-stack_v1alpha1_loraadapter.yaml
curl http://localhost:30080/v1/models | jq
```

Expected Output:

```js
{
  "object": "list",
  "data": [
    {
      "id": "meta-llama/Llama-3.1-8B-Instruct",
      "object": "model",
      "created": 1748385061,
      "owned_by": "vllm",
      "root": null,
      "parent": null
    }
  ]
}
```

Note: Remember to keep the port-forward terminal running while making these requests. You can stop it with Ctrl+C when you're done.

### 5. Troubleshooting

Common issues and solutions:

1. **Hugging Face Authentication**:
   - Verify your token is correctly set in the Kubernetes secret
   - Check pod logs for authentication errors

2. **Resource Issues**:
   - Ensure your cluster has sufficient GPU memory
   - Monitor GPU utilization using `nvidia-smi`

3. **LoRA Loading Issues**:
   - Verify LoRA weights are in the correct format
   - Check pod logs for adapter loading errors by `kubectl logs -f -n production-stack-system $(kubectl get pods -n production-stack-system | grep manager | awk '{print $1}')`

### 6. Cleanup

To remove the deployment:

```bash
helm uninstall vllm
cd operator && make undeploy
kubectl delete secret huggingface-credentials
```

## Additional Resources

- [vLLM LoRA Documentation](https://docs.vllm.ai)
- [Llama-3 Model Card](https://huggingface.co/nvidia/llama-3.1-nemoguard-8b-topic-control)
- [LoRA Paper](https://arxiv.org/abs/2106.09685)
