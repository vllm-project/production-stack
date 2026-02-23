# CRD Operator Tutorial

This tutorial explains how to deploy and manage the vLLM production stack using Custom Resource Definitions (CRDs) and the production stack operator. This approach provides better resource management, monitoring, and lifecycle management through Kubernetes operators, making it the recommended method for production environments.

## Table of Contents

- [Prerequisites](#prerequisites)

- [Overview](#overview)

- [Setup: Configure Hugging Face Token](#setup-configure-hugging-face-token)

  - [Step 1: Obtain Your Hugging Face Token](#step-1-obtain-your-hugging-face-token)

  - [Step 2: Create Kubernetes Secret](#step-2-create-kubernetes-secret)

  - [Step 3: Verify the Secret](#step-3-verify-the-secret)

- [Deploy the Operator](#deploy-the-operator)

  - [Step 1: Deploy Operator](#step-1-deploy-operator)

  - [Step 2: Verify Operator](#step-2-verify-operator)

- [Part 1: Basic Deployment](#part-1-basic-deployment)

  - [Deploy VLLMRuntime](#deploy-vllmruntime)

  - [Deploy VLLMRouter](#deploy-vllmrouter)

  - [Deploy CacheServer](#deploy-cacheserver)

  - [Verify Basic Deployment](#verify-basic-deployment)

  - [Access and Test Basic Setup](#access-and-test-basic-setup)

- [Part 2: Advanced - Disaggregated Prefill (2P2D)](#part-2-advanced---disaggregated-prefill-2p2d)

  - [Overview and Benefits](#overview-and-benefits)

  - [Deploy 2P2D Runtime](#deploy-2p2d-runtime)

  - [Deploy 2P2D Router](#deploy-2p2d-router)

  - [Verify 2P2D Deployment](#verify-2p2d-deployment)

  - [Test 2P2D Setup](#test-2p2d-setup)

  - [Cleanup 2P2D (Optional)](#cleanup-2p2d-optional)

- [Monitoring and Management](#monitoring-and-management)

  - [Check Resource Status](#check-resource-status)

  - [Update Resources](#update-resources)

  - [Delete Resources](#delete-resources)

- [Troubleshooting](#troubleshooting)

  - [Common Issues](#common-issues)

  - [Debug Commands](#debug-commands)

- [Benefits of CRD-based Deployment](#benefits-of-crd-based-deployment)

## Prerequisites

- A Kubernetes cluster with GPU support

- NVIDIA GPUs available (at least 1 GPU recommended)

- `kubectl` configured to talk to your cluster (version v1.11.3+)

- Access to a Kubernetes v1.11.3+ cluster

- A Hugging Face account and access token (for downloading gated models like Llama)

- Completion of the following setup tutorials:

  - [00-install-kubernetes-env.md](00-install-kubernetes-env.md)

## Overview

The production stack operator manages four types of custom resources:

- **VLLMRuntime**: Manages vLLM runtime instances for model serving

- **VLLMRouter**: Manages routing and load balancing between vLLM instances

- **CacheServer**: Manages cache servers for KV cache sharing

- **LoraAdapter**: Manages LoRA adapters for model fine-tuning

**Tutorial Structure:**

This tutorial is organized into two main deployment paths:

1. **Part 1: Basic Deployment** - Standard single-node deployment suitable for getting started and most production use cases. Covers:

   - Deploying a single VLLMRuntime instance

   - Setting up VLLMRouter for request routing

   - Configuring CacheServer for KV cache management

   - Testing and verification

2. **Part 2: Advanced - Disaggregated Prefill (2P2D)** - Advanced multi-node deployment that separates prefill and decode operations for higher throughput and better resource utilization. Covers:

   - Understanding disaggregated prefill architecture

   - Deploying a 2P2D setup (2 prefill + 2 decode nodes)

   - Configuring specialized routing for disaggregated operations

   - Testing KV cache transfer between nodes

Both paths require completing the initial setup sections (Prerequisites, Hugging Face Token, and Operator Deployment).

**Quick Navigation:**

| Goal | Start Here |

|------|-----------|

| First-time setup or simple deployment | Follow all sections in order through [Part 1: Basic Deployment](#part-1-basic-deployment) |

| High-throughput production deployment | Complete setup sections, then skip to [Part 2: Advanced - Disaggregated Prefill (2P2D)](#part-2-advanced---disaggregated-prefill-2p2d) |

| Understanding the architecture | Read [Overview](#overview) and [Benefits of CRD-based Deployment](#benefits-of-crd-based-deployment) |

| Troubleshooting deployment issues | Jump to [Troubleshooting](#troubleshooting) section |

## Setup: Configure Hugging Face Token

Before deploying the operator and workloads, you need to configure your Hugging Face token to access gated models (like Meta Llama models). This token will be stored as a Kubernetes Secret and referenced by the VLLMRuntime resources.

### Step 1: Obtain Your Hugging Face Token

1. Visit [Hugging Face Settings - Access Tokens](https://huggingface.co/settings/tokens)

2. Create a new token or copy an existing one

3. Make sure you have accepted the license agreements for the models you want to use (e.g., [Meta Llama models](https://huggingface.co/meta-llama))

### Step 2: Create Kubernetes Secret

Create a Kubernetes Secret to store your Hugging Face token:

```bash

# Replace YOUR_HF_TOKEN_HERE with your actual Hugging Face token

kubectl create secret generic huggingface-token \

  --from-literal=token=YOUR_HF_TOKEN_HERE

```

### Step 3: Verify the Secret

Verify that the secret was created successfully:

```bash

kubectl get secret huggingface-token

```

You should see output similar to:

```text

NAME                 TYPE     DATA   AGE

huggingface-token    Opaque   1      5s

```

**Note**: The VLLMRuntime configurations in this tutorial reference this secret as `huggingface-token`. If you use a different secret name, make sure to update the `hfTokenSecret.name` field in your VLLMRuntime configurations accordingly.

## Deploy the Operator

### Step 1: Deploy Operator

First, deploy the production stack operator to your cluster:

```bash

kubectl create -f operator/config/default.yaml

```

**Note**: If you plan to use the 2P2D (Disaggregated Prefill) feature later, make sure the CRDs include support for `enablePDDisaggregation` and `topology` fields. You can verify or update the CRDs using the instructions in the "Advanced Configuration: Disaggregated Prefill (2P2D)" section below.

This command achieves the following:

- **Namespace Creation**: Creates a namespace called `production-stack-system` where the operator will run

- **Custom Resource Definitions (CRDs)**: Defines 4 new custom resources that can be managed by this operator

- **RBAC (Role-Based Access Control)**: Creates various roles and role bindings to control access to these resources

- **Service Account**: Creates a service account `production-stack-controller-manager` for the operator

- **Deployment**: Deploys the operator controller manager as a deployment using the image `lmcache/production-stack-operator:latest`

- **Service**: Creates a metrics service for monitoring the operator

### Step 2: Verify Operator

Check that the operator is running correctly:

```bash

kubectl get pods -n production-stack-system

kubectl get crd | grep vllm.ai

```

You should see:

- The operator pod running in the `production-stack-system` namespace

- Four CRDs registered: `cacheservers`, `loraadapters`, `vllmrouters`, and `vllmruntimes`

---

## Part 1: Basic Deployment

This section demonstrates a standard deployment with single VLLMRuntime, VLLMRouter, and CacheServer instances.

**When to use this setup:**

- You're getting started with the production stack

- Your workload doesn't require extreme throughput

- You want a simpler deployment and management experience

- You have limited GPU resources (1-2 GPUs)

**What you'll deploy:**

- 1 VLLMRuntime instance (single model server)

- 1 VLLMRouter instance (for request routing)

- 1 CacheServer instance (for KV cache management)

### Deploy VLLMRuntime

Create a configuration file `vllmruntime-basic.yaml`:

```yaml

apiVersion: production-stack.vllm.ai/v1alpha1

kind: VLLMRuntime

metadata:

labels:

app.kubernetes.io/name: production-stack

model: Llama-3.1-8B-Instruct

name: vllmruntime-basic

spec:

# Model configuration

model:

modelURL: "meta-llama/Llama-3.1-8B-Instruct"

enableLoRA: false

enableTool: false

maxModelLen: 4096

dtype: "bfloat16"

maxNumSeqs: 32

# vLLM server configuration

vllmConfig:

enableChunkedPrefill: false

enablePrefixCaching: false

tensorParallelSize: 1

gpuMemoryUtilization: "0.8"

port: 8000

v1: true

# Deployment configuration

deploymentConfig:

# Resource requirements

resources:

cpu: "4"

memory: "16Gi"

gpu: "1"

# Image configuration

image:

registry: "docker.io"

name: "lmcache/vllm-openai:2025-05-27-v1"

pullPolicy: "IfNotPresent"

# Number of replicas

replicas: 1

# Storage configuration

storageConfig:

enabled: true

size: "10Gi"

```

Deploy the VLLMRuntime:

```bash

kubectl apply -f vllmruntime-basic.yaml

```

### Deploy VLLMRouter

Create a configuration file `vllmrouter-basic.yaml`:

```yaml

apiVersion: production-stack.vllm.ai/v1alpha1

kind: VLLMRouter

metadata:

labels:

app.kubernetes.io/name: production-stack

name: vllmrouter-basic

spec:

# Enable the router deployment

enableRouter: true

# Number of router replicas

replicas: 1

# Service discovery method (k8s or static)

serviceDiscovery: k8s

# Label selector for vLLM runtime pods

k8sLabelSelector: "app=vllmruntime-basic"

# Routing strategy (roundrobin or session)

routingLogic: roundrobin

# Engine statistics collection interval

engineScrapeInterval: 30

# Request statistics window

requestStatsWindow: 60

# Container port for the router service

port: 80

# Image configuration

image:

registry: docker.io

name: lmcache/lmstack-router

pullPolicy: IfNotPresent

# Resource requirements

resources:

cpu: "2"

memory: "8Gi"

```

Deploy the VLLMRouter:

```bash

kubectl apply -f vllmrouter-basic.yaml

```

### Deploy CacheServer

Create a configuration file `cacheserver-basic.yaml`:

```yaml

apiVersion: production-stack.vllm.ai/v1alpha1

kind: CacheServer

metadata:

labels:

app.kubernetes.io/name: production-stack

name: cacheserver-basic

spec:

# Enable the cache server

enabled: true

# Number of replicas

replicas: 1

# Container port

port: 8000

# Image configuration

image:

registry: docker.io

name: lmcache/lmcache-server

tag: latest

pullPolicy: IfNotPresent

# Resource requirements

resources:

cpu: "2"

memory: "4Gi"

# Storage configuration

storage:

enabled: true

size: "20Gi"

```

Deploy the CacheServer:

```bash

kubectl apply -f cacheserver-basic.yaml

```

### Verify Basic Deployment

Check the status of your deployed resources:

```bash

# Check VLLMRuntime resources

kubectl get vllmruntime vllmruntime-basic

# Check VLLMRouter resources

kubectl get vllmrouter vllmrouter-basic

# Check CacheServer resources

kubectl get cacheserver cacheserver-basic

# Check all pods

kubectl get pods -l app=vllmruntime-basic

kubectl get pods -l app=vllmrouter-basic

kubectl get pods -l app=cacheserver-basic

# View detailed status

kubectl describe vllmruntime vllmruntime-basic

```

You should see all resources in Ready state and pods Running.

### Access and Test Basic Setup

Port forward to access the VLLMRouter service:

```bash

kubectl port-forward svc/vllmrouter-basic-service 30080:80

```

Send a test request:

```bash

curl http://localhost:30080/v1/completions \

  -H "Content-Type: application/json" \

  -d '{

    "model": "meta-llama/Llama-3.1-8B-Instruct",

    "prompt": "What is the capital of France?",

    "max_tokens": 100

  }'

```

You should receive a response with the model's completion.

---

## Part 2: Advanced - Disaggregated Prefill (2P2D)

This section covers the advanced disaggregated prefill architecture, which separates the prefill phase (initial prompt processing) from the decode phase (token generation) for improved performance and scalability.

**When to use this setup:**

- You need high throughput for production workloads

- You want to optimize resource utilization for different phases

- You have sufficient GPU resources (4+ GPUs recommended)

- You need better fault tolerance and load balancing

**What you'll deploy:**

- 2 Prefill nodes (for prompt processing)

- 2 Decode nodes (for token generation)

- 1 Router with disaggregated prefill logic

- KV cache transfer infrastructure (Nixl + LMCache)

**Estimated time:** 20-30 minutes

**Prerequisites**:

- Complete the [Deploy the Operator](#deploy-the-operator) section above

- Ensure the operator is running and CRDs are properly installed

- Have at least 4 GPUs available

### Overview and Benefits

Disaggregated prefill architecture uses separate node pools for prefill and decode operations. This 2P2D setup (2 prefill nodes + 2 decode nodes) uses a unified configuration that defines both topologies in a single VLLMRuntime resource.

**Key Benefits:**

- **Higher Throughput**: Multiple prefill and decode nodes handle more concurrent requests

- **Load Balancing**: Automatic distribution of requests across multiple nodes

- **Fault Tolerance**: System continues operating if individual nodes fail

- **Resource Efficiency**: Optimized resource allocation for prefill vs decode workloads

- **Scalability**: Easy to adjust replica counts based on demand

- **KV Cache Transfer**: Seamless transfer of KV cache between prefill and decode nodes

### Deploy 2P2D Runtime

Use the provided sample configuration ([production-stack_v1alpha1_vllmruntime_2p2d.yaml](../operator/config/samples/production-stack_v1alpha1_vllmruntime_2p2d.yaml)):

```bash

kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmruntime_2p2d.yaml

```

**Note**: The sample YAML uses `storageClassName: "local-path"`. If your cluster uses a different StorageClass (e.g., `standard` for minikube), update the `storageClassName` field in both prefill and decode sections before applying:

```bash
# Check available storage classes
kubectl get sc
# Update if needed (e.g., replace local-path with standard)
sed -i 's/storageClassName: "local-path"/storageClassName: "standard"/g' operator/config/samples/production-stack_v1alpha1_vllmruntime_2p2d.yaml
```

This configuration includes:

- **2 Prefill replicas**: Running as KV producers with Nixl sender role

- **2 Decode replicas**: Running as KV consumers with Nixl receiver role

- **LMCache integration**: Configured for KV cache transfer between prefill and decode

- **LoRA support**: Enabled on both prefill and decode nodes (max 4 LoRAs)

- **Shared storage**: Both node types use persistent volumes for model caching

Key configuration highlights:

```yaml

spec:

  # Enable PD (Prefill-Decode) disaggregation

  enablePDDisaggregation: true

  # Topology configuration

  topology:

    prefill:

      deploymentConfig:

        replicas: 2  # 2 prefill nodes

      lmCacheConfig:

        kvRole: "kv_producer"

        nixlRole: "sender"

    decode:

      deploymentConfig:

        replicas: 2  # 2 decode nodes

      lmCacheConfig:

        kvRole: "kv_consumer"

        nixlRole: "receiver"

```

### Deploy 2P2D Router

Deploy the corresponding router configured for disaggregated prefill ([production-stack_v1alpha1_vllmrouter_pd.yaml](../operator/config/samples/production-stack_v1alpha1_vllmrouter_pd.yaml)):

```bash

kubectl apply -f operator/config/samples/production-stack_v1alpha1_vllmrouter_pd.yaml

```

The router configuration includes:

- **Disaggregated prefill routing logic**: Routes prefill requests to prefill nodes and decode to decode nodes

- **Nixl proxy**: Facilitates KV cache transfer coordination

- **Label-based routing**: Uses model labels to distinguish prefill and decode instances

**Important**: The sample router YAML uses `pullPolicy: Never` and a debug image tag (`lmcache/vllm-router:debug-detailed`). Before deploying, update the image to a published one, e.g.:

```yaml
  image:
    registry: docker.io
    name: lmcache/lmstack-router:latest
    pullPolicy: IfNotPresent
```

Key router configuration:

```yaml

spec:

  routingLogic: disaggregated_prefill

  k8sLabelSelector: "app=vllmruntime-pd-sample"

  extraArgs:

    - "--prefill-model-labels"

    - "Llama-3.2-1B-Instruct-prefill"

    - "--decode-model-labels"

    - "Llama-3.2-1B-Instruct-decode"

    - "--nixl-proxy-host"

    - "0.0.0.0"

    - "--nixl-proxy-port"

    - "7500"

    - "--nixl-peer-host"

    - "0.0.0.0"

    - "--nixl-peer-init-port"

    - "7300"

    - "--nixl-peer-alloc-port"

    - "7400"

```

### Verify 2P2D Deployment

Check that all components are running:

```bash

# Check the VLLMRuntime status

kubectl get vllmruntime vllmruntime-pd-sample

# Check all pods (should see 2 prefill + 2 decode = 4 runtime pods)

kubectl get pods -l app=vllmruntime-pd-sample

# Check the router

kubectl get vllmrouter vllmrouter-sample

kubectl get pods -l app=vllmrouter-sample

# View detailed status

kubectl describe vllmruntime vllmruntime-pd-sample

```

You should see:

- 4 runtime pods total (2 prefill + 2 decode)

- 1 router pod

- All pods in Running state

### Test 2P2D Setup

Port forward to access the router:

```bash

kubectl port-forward svc/vllmrouter-sample 30080:80 -n default

```

Send a test request:

```bash

curl http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "meta-llama/Llama-3.2-1B-Instruct", "prompt": "Hello!", "max_tokens": 10}'
```

The request will be automatically routed through the prefill nodes for the initial processing, and then the decode nodes will handle token generation, with KV cache seamlessly transferred between them via NIXL.

**Note**: The first request may take slightly longer as the KV transfer pipeline warms up. Subsequent requests should complete in sub-second time.

### Cleanup 2P2D (Optional)

To remove the 2P2D deployment:

```bash

kubectl delete -f operator/config/samples/production-stack_v1alpha1_vllmrouter_pd.yaml

kubectl delete -f operator/config/samples/production-stack_v1alpha1_vllmruntime_2p2d.yaml

```

## Monitoring and Management

### Check Resource Status

```bash

# Get detailed information about a VLLMRuntime

kubectl describe vllmruntime vllmruntime-basic

# Check logs of the operator

kubectl logs -n production-stack-system deployment/production-stack-controller-manager

# Check logs of a VLLMRuntime pod

kubectl logs <vllmruntime-pod-name>

```

### Update Resources

You can update any CRD resource by modifying the YAML file and applying it again:

```bash

kubectl apply -f vllmruntime-basic.yaml

```

### Delete Resources

To clean up resources:

```bash

# Delete specific resources

kubectl delete vllmruntime vllmruntime-basic

kubectl delete vllmrouter vllmrouter-basic

kubectl delete cacheserver cacheserver-basic

# Delete all resources of a type

kubectl delete vllmruntime --all

kubectl delete vllmrouter --all

kubectl delete cacheserver --all

```

## Troubleshooting

### Common Issues

1. **Operator not starting**: Check if the CRDs are properly installed and the operator has sufficient permissions.

2. **VLLMRuntime pods not starting**: Check resource availability and GPU access. Verify `storageClassName` matches your cluster's available StorageClass (`kubectl get sc`).

3. **Router cannot find backends**: Verify the label selector in the VLLMRouter matches the labels on VLLMRuntime resources.

4. **Router image pull error (2P2D)**: The sample router YAML uses `pullPolicy: Never` with a debug image. Change the image to `lmcache/lmstack-router:latest` and set `pullPolicy: IfNotPresent`.

5. **Prefill pods restarting with NIXL/UCX errors**: If you see `cuStreamCreate failed: invalid device context` in pod logs, upgrade to `lmcache/vllm-openai:latest` which includes NIXL >= 0.9.0 with the UCX CUDA context fix.

### Debug Commands

```bash

# Check operator status

kubectl get pods -n production-stack-system

# Check CRD installation

kubectl get crd | grep vllm.ai

# Check events for troubleshooting

kubectl get events --sort-by=.metadata.creationTimestamp

# Check resource status

kubectl get vllmruntime,vllmrouter,cacheserver -o wide

```

## Benefits of CRD-based Deployment

Using the CRD operator provides several advantages over direct Helm deployments:

1. **Declarative Management**: Define desired state and let the operator maintain it

2. **Lifecycle Management**: Automatic handling of updates, scaling, and recovery

3. **Resource Validation**: Built-in validation of configuration parameters

4. **Status Reporting**: Clear visibility into resource health and status

5. **Integration**: Better integration with Kubernetes ecosystem tools

6. **Consistency**: Standardized way to manage vLLM deployments across environments

This approach is recommended for production environments where you need robust, scalable, and maintainable deployments of the vLLM production stack.
