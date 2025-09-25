# Disaggregated Prefill Tutorial

This tutorial explains how to run the disaggregated prefill system, which splits the model execution into prefill and decode phases across different servers. This approach can improve throughput and resource utilization by separating the initial processing (prefill) from the token generation (decode) phases.

## Prerequisites

- A Kubernetes cluster with GPU support and NVLink enabled
- NVIDIA GPUs available (at least 2 GPUs recommended)
- `kubectl` configured to talk to your cluster
- Helm installed and initialized locally
- Completion of the following setup tutorials:
  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)
  - [01-minimal-helm-installation.md](01-minimal-helm-installation.md)

## Kubernetes Deployment

For production environments, you can deploy the disaggregated prefill system using Kubernetes and Helm. This approach provides better scalability, resource management, and high availability.

### Step 1: Create Configuration File

Create a configuration file `values-16-disagg-prefill.yaml` with the following content:

```yaml
# Unified configuration for disaggregated prefill setup
servingEngineSpec:
  enableEngine: true
  runtimeClassName: ""
  containerPort: 8000
  modelSpec:
    # Prefill node configuration
    - name: "llama-prefill"
      repository: "lmcache/vllm-openai"
      tag: "2025-05-17-v1"
      modelURL: "meta-llama/Llama-3.1-8B-Instruct"
      replicaCount: 1
      requestCPU: 8
      requestMemory: "30Gi"
      requestGPU: 1
      pvcStorage: "50Gi"
      vllmConfig:
        enableChunkedPrefill: false
        enablePrefixCaching: false
        maxModelLen: 32000
        v1: 1
      lmcacheConfig:
        enabled: true
        kvRole: "kv_producer"
        enableNixl: true
        nixlRole: "sender"
        nixlPeerHost: "pd-llama-decode-engine-service"
        nixlPeerPort: "55555"
        nixlBufferSize: "1073741824"  # 1GB
        nixlBufferDevice: "cuda"
        nixlEnableGc: true
        enablePD: true
        cpuOffloadingBufferSize: 0
      hf_token: <your-hf-token>
      labels:
        model: "llama-prefill"
    # Decode node configuration
    - name: "llama-decode"
      repository: "lmcache/vllm-openai"
      tag: "2025-05-17-v1"
      modelURL: "meta-llama/Llama-3.1-8B-Instruct"
      replicaCount: 1
      requestCPU: 8
      requestMemory: "30Gi"
      requestGPU: 1
      pvcStorage: "50Gi"
      vllmConfig:
        enableChunkedPrefill: false
        enablePrefixCaching: false
        maxModelLen: 32000
        v1: 1
      lmcacheConfig:
        enabled: true
        kvRole: "kv_consumer"
        enableNixl: true
        nixlRole: "receiver"
        nixlPeerHost: "0.0.0.0"
        nixlPeerPort: "55555"
        nixlBufferSize: "1073741824"  # 1GB
        nixlBufferDevice: "cuda"
        nixlEnableGc: true
        enablePD: true
      hf_token: <your-hf-token>
      labels:
        model: "llama-decode"
routerSpec:
  enableRouter: true
  repository: "lmcache/lmstack-router"
  tag: "pd-05-26"
  replicaCount: 1
  containerPort: 8000
  servicePort: 80
  routingLogic: "disaggregated_prefill"
  engineScrapeInterval: 15
  requestStatsWindow: 60
  enablePD: true
  resources:
    requests:
      cpu: "4"
      memory: "16G"
    limits:
      cpu: "4"
      memory: "32G"
  labels:
    environment: "router"
    release: "router"
  extraArgs:
    - "--prefill-model-labels"
    - "llama-prefill"
    - "--decode-model-labels"
    - "llama-decode"
```

### Step 2: Deploy Using Helm

Install the deployment using Helm with the configuration file:

```bash
helm install pd helm/ -f tutorials/assets/values-16-disagg-prefill.yaml
```

This will deploy:

- A prefill server with the specified configuration
- A decode server with the specified configuration
- A router to coordinate between them

The configuration includes:

- Resource requests and limits for each component
- NIXL communication settings
- Model configurations
- Router settings for disaggregated prefill

### Step 3: Verify Deployment

Check the status of your deployment:

```bash
kubectl get pods
kubectl get services
```

You should see pods for:

- The prefill server
- The decode server
- The router

### Step 4: Access the Service

First do port forwarding to access the service:

```bash
kubectl port-forward svc/pd-router-service 30080:80
```

And then send a request to the router by:

```bash
curl http://localhost:30080/v1/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "meta-llama/Llama-3.1-8B-Instruct",
        "prompt": "Your prompt here",
        "max_tokens": 100
    }'
```
