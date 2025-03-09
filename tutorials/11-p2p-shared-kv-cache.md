# Tutorial: P2P KV Cache Sharing with LMCache

## Introduction

This tutorial demonstrates how to enable P2P KV cache sharing using LMCache in a vLLM deployment. KV cache will be retrieved from another vLLM pod if the KV cache does not exist locally.
vLLM Production Stack uses LMCache for P2P KV cache sharing. For more details, see the [LMCache GitHub repository](https://github.com/LMCache/LMCache).

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Configuring P2P KV Cache Storage](#step-1-configuring-p2p-kv-cache-shared-storage)
3. [Step 2: Deploying the Helm Chart](#step-2-deploying-the-helm-chart)
4. [Step 3: Verifying the Installation](#step-3-verifying-the-installation)
5. [Benchmark the Performance Gain of P2P Shared Storage (Work in Progress)](#benchmark-the-performance-gain-of-p2p-shared-storage-work-in-progress)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
  - [02-basic-vllm-config.md](02-basic-vllm-config.md)
- A Kubernetes environment with GPU support.

## Step 1: Configuring P2P KV Cache Shared Storage

Locate the file `tutorials/assets/values-11-p2p-sharing.yaml` with the following content:

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "mistral-1"
    repository: "lmcache/vllm-openai"
    tag: "latest"
    modelURL: "mistralai/Mistral-7B-Instruct-v0.2"
    replicaCount: 2
    requestCPU: 10
    requestMemory: "40Gi"
    requestGPU: 1
    pvcStorage: "50Gi"
    vllmConfig:
      enableChunkedPrefill: false
      enablePrefixCaching: false
      maxModelLen: 16384

    lmcacheConfig:
      enabled: true
      cpuOffloadingBufferSize: "20"
      p2pEnabled: true
      distributedPort: "8200"

    hf_token: <YOUR HF TOKEN>

  - name: "mistral-2"
    repository: "lmcache/vllm-openai"
    tag: "latest"
    modelURL: "mistralai/Mistral-7B-Instruct-v0.2"
    replicaCount: 2
    requestCPU: 10
    requestMemory: "40Gi"
    requestGPU: 1
    pvcStorage: "50Gi"
    vllmConfig:
      enableChunkedPrefill: false
      enablePrefixCaching: false
      maxModelLen: 16384

    lmcacheConfig:
      enabled: true
      cpuOffloadingBufferSize: "20"
      p2pEnabled: true
      distributedPort: "8201"

    hf_token: <YOUR HF TOKEN>

lookupserverSpec:
  replicaCount: 1
  containerPort: 8080
  servicePort: 8100
  serde: "naive"

  repository: "redis"
  tag: "latest"
  resources:
    requests:
      cpu: "4"
      memory: "8G"
    limits:
      cpu: "4"
      memory: "10G"

  labels:
    environment: "lookupserver"
    release: "lookupserver"

```

> **Note:** Replace `<YOUR HF TOKEN>` with your actual Hugging Face token.

The `CacheserverSpec` starts a remote shared KV cache storage.

## Step 2: Deploying the Helm Chart

Deploy the Helm chart using the customized values file:

```bash
sudo helm install vllm vllm/vllm-stack -f tutorials/assets/values-07-shared-storage.yaml
```

## Step 3: Verifying the Installation

1. Check the pod logs to verify LMCache is active:

   ```bash
   sudo kubectl get pods
   ```

   Identify the pod name for the vLLM deployment (e.g., `vllm-mistral-1-deployment-vllm-xxxx-xxxx`). Then run:

   ```bash
   sudo kubectl logs -f <pod-name>
   ```

   Look for entries in the log indicating LMCache is enabled and operational. An example output (indicating KV cache is stored) is:

   ```plaintext
   INFO 01-21 20:16:58 lmcache_connector.py:41] Initializing LMCacheConfig under kv_transfer_config kv_connector='LMCacheConnector' kv_buffer_device='cuda' kv_buffer_size=1000000000.0 kv_role='kv_both' kv_rank=None kv_parallel_size=1 kv_ip='127.0.0.1' kv_port=14579
   INFO LMCache: Creating LMCacheEngine instance vllm-instance [2025-01-21 20:16:58,732] -- /usr/local/lib/python3.12/dist-packages/lmcache/experimental/cache_engine.py:237
   ```

2. Forward the router service port to access the stack locally:

   ```bash
   sudo kubectl port-forward svc/vllm-router-service 30080:80
   ```

3. Send a request to the stack and observe the logs:

   ```bash
   curl -X POST http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "mistralai/Mistral-7B-Instruct-v0.2",
       "prompt": "Explain the significance of KV cache in language models.",
       "max_tokens": 10
     }'
   ```

   Expected output:

   The response from the stack should contain the completion result, and the logs should show LMCache activity, for example:

   ```plaintext
   TODO
   ```

   Send another request to the stack and observe the logs:

   ```bash
   curl -X POST http://localhost:30080/v1/completions \
     -H "Content-Type: application/json" \
     -d '{
       "model": "mistralai/Mistral-7B-Instruct-v0.2",
       "prompt": "Explain the significance of KV cache in language models.",
       "max_tokens": 10
     }'
   ```

   Note that the second request will be routed to a different vLLM engine as the router is round-robin by default.

   Expected output:
   The following logs indicates that the KV cache is retrieved from another vLLM pod.

   ```plaintext
   TODO
   ```

## Benchmark the Performance Gain of P2P Shared Storage (Work in Progress)

In this section, we will benchmark the performance improvement when using LMCache for P2P KV cache storage. Note that we might need KV compression to see potential improvement. Stay tuned for updates.

## Conclusion

This tutorial demonstrated how to enable P2P KV cache sharing across multiple vllm nodes in a vLLM deployment using LMCache. Explore further configurations to tailor LMCache to your workloads.
