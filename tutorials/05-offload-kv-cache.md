# Tutorial: Offload KV Cache to CPU with LMCache

## Introduction

This tutorial demonstrates how to enable KV cache offloading using LMCache in a vLLM deployment. KV cache offloading moves large KV caches from GPU memory to CPU or disk, enabling more potential KV cache hits.
vLLM Production Stack uses LMCache for KV cache offloading. For more details, see the [LMCache GitHub repository](https://github.com/LMCache/LMCache).

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Configuring KV Cache Offloading](#step-1-configuring-kv-cache-offloading)
3. [Step 2: Deploying the Helm Chart](#step-2-deploying-the-helm-chart)
4. [Step 3: Verifying the Installation](#step-3-verifying-the-installation)
5. [Benchmark the Performance Gain of CPU Offloading (Work in Progress)](#benchmark-the-performance-gain-of-cpu-offloading-work-in-progress)

## Prerequisites

- Completion of the following tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)
  - [02-basic-vllm-config.md](02-basic-vllm-config.md)
- A Kubernetes environment with GPU support.

## Step 1: Configuring KV Cache Offloading

Locate the file `tutorials/assets/values-05-cpu-offloading.yaml` with the following content:

```yaml
servingEngineSpec:
  modelSpec:
  - name: "mistral"
    repository: "lmcache/vllm-openai"
    tag: "latest"
    modelURL: "mistralai/Mistral-7B-Instruct-v0.2"
    replicaCount: 1
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

    hf_token: <YOUR HF TOKEN>
```

> **Note:** Replace `<YOUR HF TOKEN>` with your actual Hugging Face token.

The `lmcacheConfig` field enables LMCache and sets the CPU offloading buffer size to `20`GB. You can adjust this value based on your workload.

## Step 2: Deploying the Helm Chart

Deploy the Helm chart using the customized values file:

```bash
helm install vllm vllm/vllm-stack -f tutorials/assets/values-05-cpu-offloading.yaml
```

## Step 3: Verifying the Installation

1. Check the pod logs to verify LMCache is active:

   ```bash
   sudo kubectl get pods
   ```

   Identify the pod name for the vLLM deployment (e.g., `vllm-mistral-deployment-vllm-xxxx-xxxx`). Then run:

   ```bash
   sudo kubectl logs -f <pod-name>
   ```

   Look for entries in the log indicating LMCache is enabled and operational. An example output is:

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
   curl -X POST http://localhost:30080/completions \
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
   DEBUG LMCache: Store skips 0 tokens and then stores 13 tokens [2025-01-21 20:23:45,113] -- /usr/local/lib/python3.12/dist-packages/lmcache/integration/vllm/vllm_adapter.py:490
   ```

## Benchmark the Performance Gain of CPU Offloading (Work in Progress)

In this section, we will benchmark the performance improvements when using LMCache for CPU offloading. Stay tuned for updates.

## Conclusion

This tutorial demonstrated how to enable KV cache offloading in a vLLM deployment using LMCache. By offloading KV cache to CPU, you can optimize GPU memory usage and improve the scalability of your models. Explore further configurations to tailor LMCache to your workloads.
