# Tutorial: LoRA Adapter Deployment for helm

## Introduction

This tutorial is based on the helm deployment of vllm production stack. It provides a guide to deploying and using LoRA (Low-Rank Adaptation) adapters with the vLLM Production Stack. LoRA adapters allow you to efficiently fine-tune large language models by adding small, trainable rank decomposition matrices to existing pre-trained models.

## What You'll Learn

- How to set up vLLM production stack with LoRA support
- How to deploy LoRA adapters from different sources (local, HuggingFace)
- How to manage multiple LoRA adapters
- How to test and use LoRA adapters

## Prerequisites

1. A Kubernetes cluster with GPU support
2. Helm installed
3. kubectl configured to access your cluster
4. A Hugging Face account with access to Llama-3.1-8B-Instruct
5. A valid Hugging Face token

## Architecture Overview

The LoRA deployment consists of several components:

1. **vLLM Serving Engine**: Runs the base model with LoRA support enabled
2. **LoRA Controller**: Manages the lifecycle of LoRA adapters
3. **LoRA Adapters**: Custom resources that define adapter configurations
4. **Shared Storage**: Stores LoRA adapter files

## Step 1: Deploy vLLM with LoRA Support

Locate the file [values-09-lora-helm.yaml](./assets/values-09-lora-helm.yaml) with the following content:

```yaml
# Example values file for LoRA adapter deployment
# This file shows how to configure LoRA adapters in the production-stack Helm chart
servingEngineSpec:
  runtimeClassName: ""
  strategy:
    type: Recreate
  modelSpec:
    - name: "llama3"
      repository: "vllm/vllm-openai"
      tag: "latest"
      modelURL: "meta-llama/Llama-3.1-8B-Instruct"
      enableLoRA: true

      # Option 1: Direct token
      hf_token: <your-hf-token>

      # OR Option 2: Secret reference
      # hf_token:
      #   secretName: "huggingface-credentials"
      #   secretKey: "HUGGING_FACE_HUB_TOKEN"

      # Other vLLM configs if needed
      vllmConfig:
        enablePrefixCaching: true
        maxModelLen: 4096
        dtype: "bfloat16"
        v1: 1
        extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]

      # Mount Hugging Face credentials and configure LoRA settings
      env:
        - name: VLLM_ALLOW_RUNTIME_LORA_UPDATING
          value: "True"

      replicaCount: 2

      # Resource requirements for Llama-3.1-8b
      requestCPU: 8
      requestMemory: "32Gi"
      requestGPU: 1

      pvcStorage: "10Gi"
      pvcAccessMode:
        - ReadWriteOnce

  # Shared storage for LoRA adapters
  sharedPvcStorage:
    size: "10Gi"
    storageClass: "standard"
    accessModes:
      - ReadWriteMany
    hostPath: "/data/shared-pvc-storage"

# Enable the lora controller (required for LoRA adapters)
loraController:
  enableLoraController: true
  image:
    repository: "lmcache/lmstack-lora-controller"
    tag: "latest"
    pullPolicy: "Always"

# Enable LoRA adapter functionality
loraAdapters:
    # Example 1: Local LoRA adapter
    # - name: "llama3-nemoguard-adapter"
    #   baseModel: "llama3"
    #   # Optional: vLLM API key configuration
    #   # vllmApiKey:
    #   #   secretName: "vllm-api-key"
    #   #   secretKey: "VLLM_API_KEY"
    #   adapterSource:
    #     type: "local"
    #     adapterName: "llama-3.1-nemoguard-8b-topic-control"
    #     adapterPath: "/data/shared-pvc-storage/lora-adapters/llama-3.1-nemoguard-8b-topic-control"
    #   loraAdapterDeploymentConfig:
    #     algorithm: "default" # for now we only support default algorithm
    #     replicas: 1 # if not specified, by default algorithm, the lora adapter will be applied to all llama3-8b models, if specified, the lora adapter will only be applied to the specified number of replicas

    # Example 2: HuggingFace LoRA adapter
    - name: "llama3-nemoguard-adapter"
      baseModel: "llama3"
      adapterSource:
        type: "huggingface"
        adapterName: "llama-3.1-nemoguard-8b-topic-control"
        repository: "nvidia/llama-3.1-nemoguard-8b-topic-control"
        # Optional: Credentials for repositories
        # Option 1: Direct token
        credentials: <your-hf-token>
        # Option 2: Secret reference
        # credentials:
        #   secretName: "hf-token-secret"
        #   secretKey: "HUGGING_FACE_HUB_TOKEN"

      loraAdapterDeploymentConfig:
        algorithm: "default" # for now we only support default algorithm
        replicas: 1 # if not specified, by default algorithm, the lora adapter will be applied to all llama3-8b models, if specified, the lora adapter will only be applied to the specified number of replicas

```

### 1.1 Local Lora Loading

You can manually load lora adapters to the hostpath so that it can access by the lora controller and finish loading.

```bash
minikube ssh
sudo mkdir -p /data/shared-pvc-storage/lora-adapters
python3 -c "
from huggingface_hub import snapshot_download
adapter_id = 'nvidia/llama-3.1-nemoguard-8b-topic-control'  # Example adapter
sql_lora_path = snapshot_download(
    repo_id=adapter_id,
    local_dir='/data/shared-pvc-storage/lora-adapters/llama-3.1-nemoguard-8b-topic-control',
    token=<your-hf-token>
)
"
```

Then deploy using the example 1:

```yaml
# Example values file for LoRA adapter deployment
# This file shows how to configure LoRA adapters in the production-stack Helm chart
servingEngineSpec:
  runtimeClassName: ""
  strategy:
    type: Recreate
  modelSpec:
    - name: "llama3"
      repository: "vllm/vllm-openai"
      tag: "latest"
      modelURL: "meta-llama/Llama-3.1-8B-Instruct"
      enableLoRA: true

      # Option 1: Direct token
      hf_token: <your-hf-token>

      # OR Option 2: Secret reference
      # hf_token:
      #   secretName: "huggingface-credentials"
      #   secretKey: "HUGGING_FACE_HUB_TOKEN"

      # Other vLLM configs if needed
      vllmConfig:
        enablePrefixCaching: true
        maxModelLen: 4096
        dtype: "bfloat16"
        v1: 1
        extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]

      # Mount Hugging Face credentials and configure LoRA settings
      env:
        - name: VLLM_ALLOW_RUNTIME_LORA_UPDATING
          value: "True"

      replicaCount: 2

      # Resource requirements for Llama-3.1-8b
      requestCPU: 8
      requestMemory: "32Gi"
      requestGPU: 1

      pvcStorage: "10Gi"
      pvcAccessMode:
        - ReadWriteOnce

  # Shared storage for LoRA adapters
  sharedPvcStorage:
    size: "10Gi"
    storageClass: "standard"
    accessModes:
      - ReadWriteMany
    hostPath: "/data/shared-pvc-storage"

# Enable the lora controller (required for LoRA adapters)
loraController:
  enableLoraController: true
  image:
    repository: "lmcache/lmstack-lora-controller"
    tag: "latest"
    pullPolicy: "Always"

# Enable LoRA adapter functionality
loraAdapters:
    # Example 1: Local LoRA adapter
    - name: "llama3-nemoguard-adapter"
      baseModel: "llama3"
      # Optional: vLLM API key configuration
      # vllmApiKey:
      #   secretName: "vllm-api-key"
      #   secretKey: "VLLM_API_KEY"
      adapterSource:
        type: "local"
        adapterName: "llama-3.1-nemoguard-8b-topic-control"
        adapterPath: "/data/shared-pvc-storage/lora-adapters/llama-3.1-nemoguard-8b-topic-control"
      loraAdapterDeploymentConfig:
        algorithm: "default" # for now we only support default algorithm
        replicas: 1 # if not specified, by default algorithm, the lora adapter will be applied to all llama3-8b models, if specified, the lora adapter will only be applied to the specified number of replicas

```

```bash
helm install vllm vllm/vllm-stack -f tutorials/assets/values-09-lora-helm.yaml
```

### 1.2: Huggingface Lora Loading

You can also directly load lora from huggingface by specify the adapter source type deploying with example 2.

```yaml
# Example values file for LoRA adapter deployment
# This file shows how to configure LoRA adapters in the production-stack Helm chart
servingEngineSpec:
  runtimeClassName: ""
  strategy:
    type: Recreate
  modelSpec:
    - name: "llama3"
      repository: "vllm/vllm-openai"
      tag: "latest"
      modelURL: "meta-llama/Llama-3.1-8B-Instruct"
      enableLoRA: true

      # Option 1: Direct token
      hf_token: <your-hf-token>

      # OR Option 2: Secret reference
      # hf_token:
      #   secretName: "huggingface-credentials"
      #   secretKey: "HUGGING_FACE_HUB_TOKEN"

      # Other vLLM configs if needed
      vllmConfig:
        enablePrefixCaching: true
        maxModelLen: 4096
        dtype: "bfloat16"
        v1: 1
        extraArgs: ["--disable-log-requests", "--gpu-memory-utilization", "0.8"]

      # Mount Hugging Face credentials and configure LoRA settings
      env:
        - name: VLLM_ALLOW_RUNTIME_LORA_UPDATING
          value: "True"

      replicaCount: 2

      # Resource requirements for Llama-3.1-8b
      requestCPU: 8
      requestMemory: "32Gi"
      requestGPU: 1

      pvcStorage: "10Gi"
      pvcAccessMode:
        - ReadWriteOnce

  # Shared storage for LoRA adapters
  sharedPvcStorage:
    size: "10Gi"
    storageClass: "standard"
    accessModes:
      - ReadWriteMany
    hostPath: "/data/shared-pvc-storage"

# Enable the lora controller (required for LoRA adapters)
loraController:
  enableLoraController: true
  image:
    repository: "lmcache/lmstack-lora-controller"
    tag: "latest"
    pullPolicy: "Always"

# Enable LoRA adapter functionality
loraAdapters:
    # Example 1: Local LoRA adapter
    # - name: "llama3-nemoguard-adapter"
    #   baseModel: "llama3"
    #   # Optional: vLLM API key configuration
    #   # vllmApiKey:
    #   #   secretName: "vllm-api-key"
    #   #   secretKey: "VLLM_API_KEY"
    #   adapterSource:
    #     type: "local"
    #     adapterName: "llama-3.1-nemoguard-8b-topic-control"
    #     adapterPath: "/data/shared-pvc-storage/lora-adapters/llama-3.1-nemoguard-8b-topic-control"
    #   loraAdapterDeploymentConfig:
    #     algorithm: "default"
    #     replicas: 1

    # Example 2: HuggingFace LoRA adapter
    - name: "llama3-nemoguard-adapter"
      baseModel: "llama3"
      adapterSource:
        type: "huggingface"
        adapterName: "llama-3.1-nemoguard-8b-topic-control"
        repository: "nvidia/llama-3.1-nemoguard-8b-topic-control"
        # Optional: Credentials for repositories
        # Option 1: Direct token
        credentials: <your-hf-token>
        # Option 2: Secret reference
        # credentials:
        #   secretName: "hf-token-secret"
        #   secretKey: "HUGGING_FACE_HUB_TOKEN"

      loraAdapterDeploymentConfig:
        algorithm: "default" # for now we only support default algorithm
        replicas: 1 # if not specified, by default algorithm, the lora adapter will be applied to all llama3-8b models, if specified, the lora adapter will only be applied to the specified number of replicas
```

```bash
helm install vllm vllm/vllm-stack -f tutorials/assets/values-09-lora-helm.yaml
```

## Step 2: Test vllm with LoRA support

### 2.1 Get the LoRA model info

You can get the LoRA info by querying the models endpoint

```bash
kubectl port-forward svc/vllm-router-service 30080:80
# Use another terminal
curl http://localhost:30080/v1/models | jq
```

Expected output:

```json
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

### 2.2 Generate Text with LoRA

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

## Step 3: Unload a LoRA Adapter

When finished, you can unload the adapter by delete the lora cr:

```bash
kubectl delete loraadapters.production-stack.vllm.ai llama3-nemoguard-adapter
curl http://localhost:30080/v1/models | jq
```

Expected Output:

```json
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

> **Note:** After delete the lora adapter cr, then you can delete the helm cluster. **DO NOT DELETE THE HELM RELEASE BEFORE DELETE THE ADAPTER**, Since the lora controller will be deleted and then the lora adapter cr will not be safely deleted.

```bash
helm uninstall vllm
```

Note: Remember to keep the port-forward terminal running while making these requests. You can stop it with Ctrl+C when you're done.

## Troubleshooting

1. **Hugging Face Authentication**:
   - Verify your token is correctly set in the Kubernetes secret
   - Check pod logs for authentication errors

2. **Resource Issues**:
   - Ensure your cluster has sufficient GPU memory
   - Monitor GPU utilization using `nvidia-smi`

3. **LoRA Loading Issues**:
   - Verify LoRA weights are in the correct format
   - Check LoRA Adapter files `kubectl exec -it $(kubectl get pods | grep deployment-vllm | awk '{print $1}' | head -n 1) -- ls -la /data/shared-pvc-storage/lora-adapters/`
   - Check LoRA Controller logs `kubectl logs $(kubectl get pods | grep lora-controller | awk '{print $1}' | tail -n 50)`
   - Check LoRA Adapter status `kubectl describe loraadapters.production-stack.vllm.ai llama3-nemoguard-adapter`

## Additional Resources

- [vLLM LoRA Documentation](https://docs.vllm.ai/en/latest/models/lora.html)
- [HuggingFace LoRA Adapters](https://huggingface.co/models?search=lora)
- [Production Stack Documentation](https://docs.vllm.ai/en/latest/deployment/index.html)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)

## Conclusion

This tutorial has covered the complete process of deploying and using LoRA adapters with the vLLM Production Stack. You now have a working setup that can load and use LoRA adapters from both local storage and HuggingFace Hub. The system is designed to be scalable and production-ready, with proper monitoring and troubleshooting capabilities.
