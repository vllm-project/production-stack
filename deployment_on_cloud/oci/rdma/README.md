# RDMA Multi-Node Deployment on OCI

This guide covers deploying vLLM with RDMA (Remote Direct Memory Access) cluster networking on Oracle Cloud Infrastructure for multi-node pipeline parallelism.

## Overview

OCI provides RDMA over Converged Ethernet v2 (RoCEv2) networking with:
- 2-6.5 microsecond latency (vs 50-100 microseconds for standard networking)
- Up to 1.6 Tbps aggregate bandwidth per node
- Direct GPU-to-GPU communication via GPUDirect RDMA

This enables efficient multi-node inference for models too large for a single node (e.g., Llama 3.1 405B).

## Prerequisites

- OKE cluster with bare metal GPU nodes (BM.GPU.H100.8 or BM.GPU.A100-v2.8)
- Cluster Network configured for RDMA
- At least 2 GPU nodes in the same cluster network

## Supported Shapes

| Shape | GPUs | RDMA NICs | Bandwidth |
|-------|------|-----------|-----------|
| BM.GPU.H100.8 | 8x H100 | 8x 200 Gbps | 1.6 Tbps |
| BM.GPU.A100-v2.8 | 8x A100 80GB | 8x 100 Gbps | 800 Gbps |
| BM.GPU4.8 | 8x A100 40GB | 8x 100 Gbps | 800 Gbps |

## Step 1: Create Cluster Network

Create a cluster network for RDMA connectivity:

```bash
# Create cluster network placement group
CLUSTER_NETWORK_ID=$(oci compute cluster-network create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --availability-domain "${AD}" \
    --display-name "vllm-rdma-cluster" \
    --instance-pools "[{
        \"size\": 2,
        \"instanceConfigurationId\": \"${INSTANCE_CONFIG_ID}\",
        \"displayName\": \"gpu-pool\"
    }]" \
    --placement-configuration "{
        \"availabilityDomain\": \"${AD}\",
        \"primarySubnetId\": \"${WORKER_SUBNET_ID}\"
    }" \
    --query "data.id" \
    --raw-output)
```

## Step 2: Configure Instance Configuration

Create an instance configuration for RDMA-enabled GPU nodes:

```bash
INSTANCE_CONFIG_ID=$(oci compute-management instance-configuration create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --display-name "vllm-rdma-config" \
    --instance-details "{
        \"instanceType\": \"compute\",
        \"launchDetails\": {
            \"compartmentId\": \"${OCI_COMPARTMENT_ID}\",
            \"shape\": \"BM.GPU.H100.8\",
            \"sourceDetails\": {
                \"sourceType\": \"image\",
                \"imageId\": \"${GPU_IMAGE_ID}\"
            },
            \"createVnicDetails\": {
                \"subnetId\": \"${WORKER_SUBNET_ID}\",
                \"assignPublicIp\": false
            }
        }
    }" \
    --query "data.id" \
    --raw-output)
```

## Step 3: Configure NCCL Environment

For RDMA communication, configure NCCL environment variables in your Helm values:

```yaml
# cluster-network-config.yaml
servingEngineSpec:
  modelSpec:
  - name: "llama405b"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-405B-Instruct"

    replicaCount: 1
    tensorParallelSize: 8
    pipelineParallelSize: 2  # 2 nodes

    requestCPU: 64
    requestMemory: "512Gi"
    requestGPU: 8

    # NCCL and RDMA configuration
    env:
      # NCCL settings for RDMA
      - name: NCCL_IB_HCA
        value: "mlx5"
      - name: NCCL_IB_GID_INDEX
        value: "3"
      - name: NCCL_IB_SL
        value: "0"
      - name: NCCL_IB_TC
        value: "41"
      - name: NCCL_IB_QPS_PER_CONNECTION
        value: "4"
      - name: NCCL_NET_GDR_LEVEL
        value: "5"
      - name: NCCL_NET_GDR_READ
        value: "1"
      - name: NCCL_SOCKET_IFNAME
        value: "eth0"
      - name: NCCL_DEBUG
        value: "INFO"

      # vLLM distributed settings
      - name: VLLM_HOST_IP
        valueFrom:
          fieldRef:
            fieldPath: status.podIP

    nodeSelector:
      cluster-network: "vllm-rdma-cluster"

    tolerations:
      - key: "nvidia.com/gpu"
        operator: "Exists"
        effect: "NoSchedule"

    extraArgs:
      - "--max-model-len=8192"
      - "--gpu-memory-utilization=0.95"
      - "--tensor-parallel-size=8"
      - "--pipeline-parallel-size=2"
      - "--distributed-executor-backend=ray"
```

## Step 4: Deploy with Ray for Multi-Node

For multi-node deployments, use Ray as the distributed executor:

```yaml
# Add Ray head service
apiVersion: v1
kind: Service
metadata:
  name: ray-head
spec:
  ports:
    - name: client
      port: 10001
      targetPort: 10001
    - name: dashboard
      port: 8265
      targetPort: 8265
    - name: gcs
      port: 6379
      targetPort: 6379
  selector:
    app: ray-head
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ray-head
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ray-head
  template:
    metadata:
      labels:
        app: ray-head
    spec:
      containers:
      - name: ray-head
        image: rayproject/ray:2.9.0-py310-gpu
        ports:
          - containerPort: 10001
          - containerPort: 8265
          - containerPort: 6379
        command: ["ray", "start", "--head", "--port=6379", "--dashboard-host=0.0.0.0"]
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
```

## Step 5: Verify RDMA Connectivity

Check RDMA devices on nodes:

```bash
kubectl exec -it <pod-name> -- ibv_devices
```

Expected output:

```plaintext
    device                 node GUID
    ------              ----------------
    mlx5_0              0015417f0131a0ca
    mlx5_1              0015417f0131a0cb
    ...
```

Verify NCCL can use RDMA:

```bash
kubectl exec -it <pod-name> -- bash -c "NCCL_DEBUG=INFO python -c 'import torch.distributed'"
```

## Performance Tuning

### Network Settings

```yaml
env:
  # Optimize for large messages
  - name: NCCL_BUFFSIZE
    value: "2097152"
  # Use multiple connections
  - name: NCCL_MIN_NCHANNELS
    value: "4"
  - name: NCCL_MAX_NCHANNELS
    value: "8"
```

### Memory Settings

```yaml
env:
  # Enable huge pages for better memory performance
  - name: NCCL_SHM_USE_CUDA_MEMCPY
    value: "1"
```

## Troubleshooting

### NCCL Timeout

If you see NCCL timeout errors:

```bash
# Increase timeout
env:
  - name: NCCL_TIMEOUT
    value: "600"
```

### RDMA Not Detected

Verify RDMA kernel modules:

```bash
kubectl exec -it <pod-name> -- lsmod | grep mlx
```

Check for proper network configuration:

```bash
kubectl exec -it <pod-name> -- ibstat
```

## References

- [OCI Cluster Networking](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/managingclusternetworks.htm)
- [NCCL Documentation](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/)
- [vLLM Distributed Inference](https://docs.vllm.ai/en/latest/serving/distributed_serving.html)
