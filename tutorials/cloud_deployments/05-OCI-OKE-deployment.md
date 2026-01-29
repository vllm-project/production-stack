# Deploying vLLM production-stack on Oracle Cloud OKE

This guide walks you through deploying the vLLM production-stack on Oracle Kubernetes Engine (OKE). It covers creating an OKE cluster with GPU nodes, configuring OCI Block Volumes for model storage, and deploying the vLLM inference stack using Helm.

## Installing Prerequisites

Before running this setup, ensure you have:

1. [OCI CLI](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm) installed and configured with `oci setup config`
2. [jq](https://jqlang.github.io/jq/download/) for JSON parsing
3. [Kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)
4. [Helm](https://helm.sh/docs/intro/install/)
5. GPU quota in your OCI tenancy (request via support ticket if needed)

## TL;DR

> [!CAUTION]
> This script requires GPU cloud resources and will incur costs. Please make sure all resources are shut down properly.

To run the service, go into the `deployment_on_cloud/oci` folder and run:

```bash
cd deployment_on_cloud/oci
export OCI_COMPARTMENT_ID="ocid1.compartment.oc1..xxxxx"
./entry_point.sh setup ./production_stack_specification.yaml
```

Clean up the service with:

```bash
./entry_point.sh cleanup
```

## Step by Step Explanation

### Step 1: Configure Environment Variables

Set the required OCI configuration:

```bash
# Required: Your OCI compartment OCID
export OCI_COMPARTMENT_ID="ocid1.compartment.oc1..xxxxx"

# Optional: Override defaults
export OCI_REGION="us-ashburn-1"
export CLUSTER_NAME="production-stack"
export GPU_SHAPE="VM.GPU.A10.1"
export GPU_NODE_COUNT="1"
```

You can find your compartment OCID in the OCI Console under Identity > Compartments.

### Step 2: Create VCN and Networking

The script automatically creates networking resources:

```bash
# Create VCN
VCN_ID=$(oci network vcn create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --display-name "${CLUSTER_NAME}-vcn" \
    --cidr-blocks '["10.0.0.0/16"]' \
    --dns-label "prodstack" \
    --query "data.id" \
    --raw-output)

# Create Internet Gateway
IGW_ID=$(oci network internet-gateway create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --vcn-id "${VCN_ID}" \
    --display-name "${CLUSTER_NAME}-igw" \
    --is-enabled true \
    --query "data.id" \
    --raw-output)

# Create Route Table with internet access
RT_ID=$(oci network route-table create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --vcn-id "${VCN_ID}" \
    --display-name "${CLUSTER_NAME}-rt" \
    --route-rules "[{\"cidrBlock\": \"0.0.0.0/0\", \"networkEntityId\": \"${IGW_ID}\"}]" \
    --query "data.id" \
    --raw-output)

# Create subnets for workers, load balancers, and API endpoint
# (See entry_point.sh for full implementation)
```

### Step 3: Deploy the OKE Cluster

Create an OKE cluster with the OCI CLI:

```bash
# Check OCI documentation for supported Kubernetes versions
CLUSTER_ID=$(oci ce cluster create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --name "${CLUSTER_NAME}" \
    --vcn-id "${VCN_ID}" \
    --kubernetes-version "v1.31.10" \
    --endpoint-subnet-id "${API_SUBNET_ID}" \
    --service-lb-subnet-ids "[\"${LB_SUBNET_ID}\"]" \
    --endpoint-public-ip-enabled true \
    --query "data.id" \
    --raw-output)

# Wait for cluster to be ready
oci ce cluster get --cluster-id "${CLUSTER_ID}" --wait-for-state ACTIVE
```

### Step 4: Add GPU Node Pool

Add a node pool with GPU instances:

```bash
oci ce node-pool create \
    --compartment-id "${OCI_COMPARTMENT_ID}" \
    --cluster-id "${CLUSTER_ID}" \
    --name "gpu-pool" \
    --kubernetes-version "v1.31.10" \
    --node-shape "VM.GPU.A10.1" \
    --size 1 \
    --placement-configs "[{\"availabilityDomain\": \"${AD}\", \"subnetId\": \"${WORKER_SUBNET_ID}\"}]" \
    --initial-node-labels '[{"key": "app", "value": "gpu"}, {"key": "nvidia.com/gpu", "value": "true"}]'
```

#### Available GPU Shapes

| Shape | GPUs | GPU Type | GPU Memory | Use Case |
|-------|------|----------|------------|----------|
| `VM.GPU.A10.1` | 1 | A10 | 24GB | 7B-13B models |
| `VM.GPU.A10.2` | 2 | A10 | 48GB | Tensor parallel small models |
| `BM.GPU4.8` | 8 | A100 40GB | 320GB | 70B models, cost-effective |
| `BM.GPU.A100-v2.8` | 8 | A100 80GB | 640GB | 70B+ models |
| `BM.GPU.H100.8` | 8 | H100 | 640GB | Largest models, RDMA support |

### Step 5: Configure kubectl

Download the kubeconfig for your OKE cluster:

```bash
oci ce cluster create-kubeconfig \
    --cluster-id "${CLUSTER_ID}" \
    --file "${HOME}/.kube/config" \
    --region "${OCI_REGION}" \
    --token-version 2.0.0 \
    --kube-endpoint PUBLIC_ENDPOINT

# Verify nodes are ready
kubectl get nodes
```

Expected output:

```plaintext
NAME          STATUS   ROLES   AGE   VERSION
10.0.10.2     Ready    node    5m    v1.31.10
```

> **Note**: The `entry_point.sh` script defaults to creating a **private cluster** for security. Private clusters require a bastion and SSH tunnel to access. See the [README.md](../../deployment_on_cloud/oci/README.md) for detailed instructions on setting up bastion access.

### Step 6: Install NVIDIA Device Plugin

Deploy the NVIDIA device plugin to expose GPUs to Kubernetes:

```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

# Verify GPUs are detected
kubectl get nodes -o="custom-columns=NAME:.metadata.name,GPUs:.status.capacity.nvidia\.com/gpu"
```

Expected output:

```plaintext
NAME          GPUs
10.0.10.2     1
```

### Step 7: Configure Storage

Apply the OCI Block Volume StorageClass:

```bash
kubectl apply -f oci-block-storage-sc.yaml
```

The StorageClass configuration:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: oci-block-storage-enc
provisioner: blockvolume.csi.oraclecloud.com
parameters:
  vpusPerGB: "10"  # Balanced performance
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
```

### Step 8: Expand GPU Node Filesystem (CRITICAL)

> **Important**: OCI boot volumes have a ~47GB partition regardless of the volume size you specify. You **must** expand the filesystem before deploying vLLM, as the container image is ~10GB.

```bash
# Use the entry_point.sh helper
./entry_point.sh expand-disk
```

Or manually expand using a privileged pod (see [README.md](../../deployment_on_cloud/oci/README.md#step-10-expand-gpu-node-filesystem-critical) for full instructions).

The expansion process runs these 4 steps in order:

1. `growpart /dev/sda 3` - Expand partition
2. `pvresize /dev/sda3` - Resize LVM physical volume
3. `lvextend -l +100%FREE /dev/ocivolume/root` - Extend logical volume
4. `xfs_growfs /` - Grow XFS filesystem

After expansion, verify the filesystem is ~180GB+:

```bash
kubectl exec -it <vllm-pod> -- df -h /
```

### Step 9: Deploy the vLLM Stack

Add the Helm repository and deploy:

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm repo update

helm upgrade -i --wait \
    vllm vllm/vllm-stack \
    -f production_stack_specification.yaml
```

Example `production_stack_specification.yaml` for OCI:

```yaml
servingEngineSpec:
  runtimeClassName: ""
  modelSpec:
  - name: "llama8b"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-8B-Instruct"

    replicaCount: 1
    requestCPU: 4
    requestMemory: "16Gi"
    requestGPU: 1

    # Create a secret: kubectl create secret generic hf-token-secret --from-literal=token=YOUR_HUGGINGFACE_TOKEN
    hf_token:
      secretName: "hf-token-secret"
      secretKey: "token"

    pvcStorage: "100Gi"
    pvcAccessMode:
      - ReadWriteOnce
    storageClass: "oci-block-storage-enc"

    nodeSelector:
      app: gpu
    tolerations:
      - key: "nvidia.com/gpu"
        operator: "Exists"
        effect: "NoSchedule"

    extraArgs:
      - "--max-model-len=4096"
      - "--gpu-memory-utilization=0.90"
```

Verify the deployment:

```bash
kubectl get pods
```

Expected output:

```plaintext
NAME                                         READY   STATUS    RESTARTS   AGE
vllm-deployment-router-6786bdcc5b-abc12      1/1     Running   0          2m
vllm-llama8b-deployment-vllm-7dd564bc8f-xyz  1/1     Running   0          2m
```

### Step 10: Test the Inference Endpoint

Get the service endpoint:

```bash
kubectl get svc
```

Port forward to test locally:

```bash
kubectl port-forward svc/vllm-deployment-router 8000:80
```

Send a test request:

```bash
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama8b",
    "prompt": "Hello, how are you?",
    "max_tokens": 50
  }'
```

### Step 11: Expose via OCI Load Balancer (Optional)

To expose the service externally, modify the service type:

```bash
kubectl patch svc vllm-deployment-router -p '{"spec": {"type": "LoadBalancer"}}'

# Wait for external IP
kubectl get svc vllm-deployment-router -w
```

### Step 12: Clean Up

Remove the Helm release:

```bash
helm uninstall vllm
kubectl delete pvc -l app.kubernetes.io/instance=vllm
```

Delete all OCI resources:

```bash
./entry_point.sh cleanup
```

## Advanced: Multi-GPU Tensor Parallelism

For larger models on bare metal GPU shapes, configure tensor parallelism:

```yaml
servingEngineSpec:
  modelSpec:
  - name: "llama70b"
    repository: "vllm/vllm-openai"
    tag: "latest"
    modelURL: "meta-llama/Llama-3.1-70B-Instruct"

    replicaCount: 1
    tensorParallelSize: 8

    requestCPU: 32
    requestMemory: "256Gi"
    requestGPU: 8

    nodeSelector:
      node.kubernetes.io/instance-type: "BM.GPU.H100.8"

    extraArgs:
      - "--max-model-len=8192"
      - "--gpu-memory-utilization=0.95"
      - "--tensor-parallel-size=8"
```

## Advanced: Using OCI Object Storage for Models

Instead of downloading from Hugging Face, you can use OCI Object Storage with Pre-Authenticated Requests (PAR):

1. Upload your model to OCI Object Storage bucket
2. Create a PAR URL for the bucket
3. Configure vLLM to download from PAR:

```yaml
env:
  - name: BUCKET_PAR_URL
    value: "https://objectstorage.us-ashburn-1.oraclecloud.com/p/xxx/n/namespace/b/bucket/o"
  - name: MODEL_NAME
    value: "your-model-name"
```

## Summary

This tutorial covers:

- Creating an OKE cluster with GPU nodes
- Configuring OCI Block Volume storage
- Installing NVIDIA device plugin
- **Expanding the GPU node filesystem** (critical for OCI)
- Deploying the vLLM production stack with Helm
- Testing the inference endpoint
- Cleaning up resources

For detailed troubleshooting and advanced configuration (private clusters, bastion access, disk expansion issues), see the comprehensive [README.md](../../deployment_on_cloud/oci/README.md).

Now your Oracle Cloud OKE production-stack is ready for large-scale AI model deployment!
