<!-- TOC ignore:true -->
# Tutorial: Setting up vLLM with Llama-3.1 and LoRA Support

<!-- TOC -->

- [Tutorial: Setting up vLLM with Llama-3.1 and LoRA Support](#tutorial-setting-up-vllm-with-llama-31-and-lora-support)
  - [Introduction](#introduction)
  - [Prerequisites](#prerequisites)
  - [Architecture Overview](#architecture-overview)
  - [Approach 1: Operator-based Deployment](#approach-1-operator-based-deployment)
    - [Step 1: Set up Hugging Face Credentials](#step-1-set-up-hugging-face-credentials)
    - [Step 2: Deploy vLLM Instance with LoRA Support](#step-2-deploy-vllm-instance-with-lora-support)
    - [Step 3: Using LoRA Adapters](#step-3-using-lora-adapters)
  - [Approach 2: Helm-based Deployment](#approach-2-helm-based-deployment)
    - [Step 1: Deploy vLLM with LoRA Support](#step-1-deploy-vllm-with-lora-support)
    - [Step 2: LoRA loading](#step-2-lora-loading)
    - [Step 3: Test vLLM with LoRA Support](#step-3-test-vllm-with-lora-support)
    - [Step 4: Unload a LoRA Adapter](#step-4-unload-a-lora-adapter)
  - [Cleanup](#cleanup)
    - [For Operator-based Deployment](#for-operator-based-deployment)
    - [For Helm-based Deployment](#for-helm-based-deployment)
  - [Troubleshooting](#troubleshooting)
  - [Additional Resources](#additional-resources)
  - [Conclusion](#conclusion)

<!-- /TOC -->

## Introduction

This tutorial guides you through setting up the vLLM Production Stack with Llama-3.1-8b-Instruct and LoRA adapter support. This setup enables you to use and switch between different LoRA adapters at runtime. We'll cover two deployment approaches:

1. **Operator-based deployment** - Using Kubernetes Custom Resources (CRDs)
2. **Helm-based deployment** - Using Helm charts with built-in LoRA support

## Prerequisites

1. All prerequisites from the [minimal installation tutorial](01-minimal-helm-installation.md)
2. A Hugging Face account with access to Llama-3.1-8b-Instruct

## Architecture Overview

The LoRA deployment consists of several components:

1. **vLLM Serving Engine**: Runs the base model with LoRA support enabled
2. **LoRA Controller**: Manages the lifecycle of LoRA adapters
3. **LoRA Adapters**: Custom resources that define adapter configurations
4. **Shared Storage**: Stores LoRA adapter files

## Approach 1: Operator-based Deployment

### Step 1: Set up Hugging Face Credentials

First, create a Kubernetes secret with your Hugging Face token:

```bash
kubectl create secret generic huggingface-credentials \
  --from-literal=HUGGING_FACE_HUB_TOKEN=your_token_here
```

### Step 2: Deploy vLLM Instance with LoRA Support

<!-- TOC ignore:true -->
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

<!-- TOC ignore:true -->
#### 2.2: Deploy the Helm Chart

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm install vllm vllm/vllm-stack -f tutorials/assets/values-09-lora-enabled.yaml
```

### Step 3: Using LoRA Adapters

<!-- TOC ignore:true -->
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
    token=__import__('os').environ['HF_TOKEN']
)
"

# Verify the adapter files are downloaded
ls -l /data/lora-adapters/
```

<!-- TOC ignore:true -->
#### 3.2: Install the operator

```bash
cd operator
make deploy IMG=lmcache/operator:latest
```

<!-- TOC ignore:true -->
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

<!-- TOC ignore:true -->
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

<!-- TOC ignore:true -->
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

## Approach 2: Helm-based Deployment

### Step 1: Deploy vLLM with LoRA Support

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

### Step 2: LoRA loading

<!-- TOC ignore:true -->
#### 2.1 Local LoRA Loading

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

Then deploy using the example 1 configuration:

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

<!-- TOC ignore:true -->
#### 2.2 HuggingFace LoRA Loading

You can also directly load lora from huggingface by specify the adapter source type deploying with example 2 configuration:

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

### Step 3: Test vLLM with LoRA Support

<!-- TOC ignore:true -->
#### 3.1: Get the LoRA model info

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

<!-- TOC ignore:true -->
#### 3.2: Generate Text with LoRA

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

### Step 4: Unload a LoRA Adapter

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

Note: Remember to keep the port-forward terminal running while making these requests. You can stop it with Ctrl+C when you're done.

## Cleanup

### For Operator-based Deployment

```bash
helm uninstall vllm
cd operator && make undeploy
kubectl delete secret huggingface-credentials
```

### For Helm-based Deployment

```bash
# First delete any LoRA adapters
kubectl delete loraadapters.production-stack.vllm.ai --all
# Then uninstall the Helm release
helm uninstall vllm
```

> **Note:** After delete the lora adapter cr, then you can delete the helm cluster. **DO NOT DELETE THE HELM RELEASE BEFORE DELETE THE ADAPTER**, Since the lora controller will be deleted and then the lora adapter cr will not be safely deleted.

## Troubleshooting

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
   - Check LoRA Adapter files `kubectl exec -it $(kubectl get pods | grep deployment-vllm | awk '{print $1}' | head -n 1) -- ls -la /data/shared-pvc-storage/lora-adapters/`
   - Check LoRA Controller logs `kubectl logs $(kubectl get pods | grep lora-controller | awk '{print $1}' | tail -n 50)`
   - Check LoRA Adapter status `kubectl describe loraadapters.production-stack.vllm.ai llama3-nemoguard-adapter`

## Additional Resources

- [vLLM LoRA Documentation](https://docs.vllm.ai/en/latest/models/lora.html)
- [Llama-3 Model Card](https://huggingface.co/nvidia/llama-3.1-nemoguard-8b-topic-control)
- [LoRA Paper](https://arxiv.org/abs/2106.09685)
- [HuggingFace LoRA Adapters](https://huggingface.co/models?search=lora)
- [Production Stack Documentation](https://docs.vllm.ai/en/latest/deployment/index.html)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)

## Conclusion

This tutorial has covered the complete process of deploying and using LoRA adapters with the vLLM Production Stack using both operator-based and Helm-based approaches. You now have a working setup that can load and use LoRA adapters from both local storage and HuggingFace Hub. The system is designed to be scalable and production-ready, with proper monitoring and troubleshooting capabilities.

Choose the approach that best fits your deployment strategy and operational requirements.
