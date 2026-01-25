# Deploying vLLM Production Stack on Oracle Cloud Infrastructure (OCI)

This guide provides a complete walkthrough for deploying the vLLM production stack on Oracle Kubernetes Engine (OKE) with GPU support.

---

## Important Notice

> **This script and documentation are provided as a reference implementation and best practices guide.**
>
> - **Recommended approach**: Execute each step manually first to understand the process
> - **Every environment is different**: OCI regions, availability domains, quotas, and network configurations vary
> - **Test before automating**: Only run the full script (`./entry_point.sh setup`) after you have successfully executed the entire process step-by-step at least once
> - **Costs apply**: GPU instances incur significant costs (~$50/day for A10). Always clean up resources when not in use.

---

## Prerequisites

### Required Knowledge

Before proceeding, you should have working knowledge of:

| Area | Required Skills |
|------|-----------------|
| **Kubernetes** | kubectl commands, pods, deployments, services, PVCs, node management, troubleshooting |
| **OCI** | Compartments, VCNs, subnets, compute shapes, OKE basics, Bastion service, IAM policies |
| **Networking** | SSH tunnels, port forwarding, private vs public endpoints |
| **Linux** | Bash scripting, LVM, filesystem management |

### Required Tools

Install these tools before starting:

```bash
# OCI CLI - https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm
brew install oci-cli  # macOS
# or
pip install oci-cli

# Kubernetes CLI
brew install kubectl  # macOS
# or see https://kubernetes.io/docs/tasks/tools/

# Helm
brew install helm  # macOS
# or see https://helm.sh/docs/intro/install/

# jq (JSON parsing)
brew install jq  # macOS
```

### OCI Configuration

1. **OCI CLI Profile**: Configure your OCI CLI with API key authentication:

   ```bash
   oci setup config
   ```

2. **Compartment**: Identify or create a compartment for your resources:

   ```bash
   oci iam compartment list --query 'data[*].{name:name, id:id}' --output table
   ```

3. **GPU Quota**: Ensure you have GPU quota in your tenancy. Request via OCI Support if needed.

4. **SSH Key**: Have an SSH key pair ready for bastion access:

   ```bash
   # Generate if you don't have one
   ssh-keygen -t rsa -b 2048 -f ~/.ssh/id_rsa_oci
   ```

---

## Architecture Overview

```text
                                    ┌─────────────────────────────────────────┐
                                    │              OCI Region                  │
                                    │                                          │
┌──────────┐    SSH Tunnel          │  ┌─────────────┐    ┌─────────────────┐ │
│  Your    │◄───────────────────────┼──│   Bastion   │    │   OKE Cluster   │ │
│ Machine  │    Port 6443           │  │   Service   │    │   (Private)     │ │
└──────────┘                        │  └─────────────┘    │                 │ │
                                    │                      │  ┌───────────┐ │ │
                                    │                      │  │ CPU Node  │ │ │
                                    │                      │  │ (kube-sys)│ │ │
                                    │                      │  └───────────┘ │ │
                                    │                      │                 │ │
                                    │                      │  ┌───────────┐ │ │
                                    │                      │  │ GPU Node  │ │ │
                                    │                      │  │ (A10 24GB)│ │ │
                                    │                      │  │           │ │ │
                                    │                      │  │ ┌───────┐ │ │ │
                                    │                      │  │ │ vLLM  │ │ │ │
                                    │                      │  │ │ Pod   │ │ │ │
                                    │                      │  │ └───────┘ │ │ │
                                    │                      │  └───────────┘ │ │
                                    │                      └─────────────────┘ │
                                    └─────────────────────────────────────────┘
```

---

## Step-by-Step Deployment Guide

### Step 1: Set Environment Variables

```bash
cd deployment_on_cloud/oci/

# Required
export OCI_COMPARTMENT_ID="ocid1.compartment.oc1..your-compartment-id"

# Optional (with defaults)
export OCI_PROFILE="DEFAULT"           # Your OCI CLI profile
export OCI_REGION="us-ashburn-1"       # Target region
export CLUSTER_NAME="vllm-production"  # Cluster name
export GPU_SHAPE="VM.GPU.A10.1"        # GPU shape (1x A10 24GB)
export GPU_BOOT_VOLUME_GB="200"        # Boot volume for model storage
export GPU_AD_INDEX="1"                # Availability Domain index (see below)
```

### Step 2: Check GPU Availability

**Critical**: A10 GPUs are NOT available in all Availability Domains.

```bash
# List availability domains
oci iam availability-domain list \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --query 'data[*].name' --output table

# Check GPU availability in each AD
AD="Jzji:US-ASHBURN-AD-2"  # Replace with your AD
oci compute shape list \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --availability-domain "${AD}" \
  --query 'data[?contains(shape, `GPU`)].shape' --output table
```

**Known GPU Availability:**

| Region | A10 Available In |
|--------|------------------|
| us-ashburn-1 | AD-2, AD-3 (use `GPU_AD_INDEX=1` or `2`) |
| us-chicago-1 | AD-1 only (use `GPU_AD_INDEX=0`) |

### Step 3: Create Network Infrastructure (VCN)

```bash
# Create VCN
VCN_ID=$(oci network vcn create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --cidr-blocks '["10.0.0.0/16"]' \
  --display-name "${CLUSTER_NAME}-vcn" \
  --query 'data.id' --raw-output)

echo "VCN ID: ${VCN_ID}"

# Create Internet Gateway
IGW_ID=$(oci network internet-gateway create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --is-enabled true \
  --display-name "${CLUSTER_NAME}-igw" \
  --query 'data.id' --raw-output)

# Create NAT Gateway (for private cluster)
NAT_ID=$(oci network nat-gateway create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --display-name "${CLUSTER_NAME}-nat" \
  --query 'data.id' --raw-output)

# Create Service Gateway
SG_ID=$(oci network service-gateway create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --services "[{\"serviceId\": \"$(oci network service list --profile ${OCI_PROFILE} --query 'data[?contains(name, `All`)].id | [0]' --raw-output)\"}]" \
  --display-name "${CLUSTER_NAME}-sg" \
  --query 'data.id' --raw-output)
```

### Step 4: Create Subnets

```bash
# Worker Subnet (private)
WORKER_SUBNET=$(oci network subnet create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --cidr-block "10.0.10.0/24" \
  --display-name "${CLUSTER_NAME}-worker-subnet" \
  --prohibit-public-ip-on-vnic true \
  --query 'data.id' --raw-output)

# API Endpoint Subnet (private)
API_SUBNET=$(oci network subnet create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --cidr-block "10.0.0.0/28" \
  --display-name "${CLUSTER_NAME}-api-subnet" \
  --prohibit-public-ip-on-vnic true \
  --query 'data.id' --raw-output)

# Load Balancer Subnet (public)
LB_SUBNET=$(oci network subnet create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --cidr-block "10.0.20.0/24" \
  --display-name "${CLUSTER_NAME}-lb-subnet" \
  --query 'data.id' --raw-output)

# Bastion Subnet (public)
BASTION_SUBNET=$(oci network subnet create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --cidr-block "10.0.30.0/24" \
  --display-name "${CLUSTER_NAME}-bastion-subnet" \
  --query 'data.id' --raw-output)
```

### Step 5: Create OKE Cluster

```bash
# Get Kubernetes version
K8S_VERSION="v1.31.10"

# Create cluster with private endpoint
CLUSTER_ID=$(oci ce cluster create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --vcn-id ${VCN_ID} \
  --kubernetes-version ${K8S_VERSION} \
  --name ${CLUSTER_NAME} \
  --endpoint-subnet-id ${API_SUBNET} \
  --service-lb-subnet-ids "[\"${LB_SUBNET}\"]" \
  --endpoint-public-ip-enabled false \
  --query 'data.id' --raw-output)

echo "Cluster ID: ${CLUSTER_ID}"
echo "Waiting for cluster to become ACTIVE (10-15 minutes)..."

# Wait for cluster
while true; do
  STATE=$(oci ce cluster get --profile ${OCI_PROFILE} --cluster-id ${CLUSTER_ID} --query 'data."lifecycle-state"' --raw-output)
  echo "  State: ${STATE}"
  [[ "${STATE}" == "ACTIVE" ]] && break
  sleep 30
done
```

### Step 6: Create Bastion Service

```bash
BASTION_ID=$(oci bastion bastion create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --bastion-type STANDARD \
  --target-subnet-id ${WORKER_SUBNET} \
  --client-cidr-block-allow-list '["0.0.0.0/0"]' \
  --name "${CLUSTER_NAME}-bastion" \
  --query 'data.id' --raw-output)

echo "Bastion ID: ${BASTION_ID}"
echo "Waiting for bastion to become ACTIVE..."

while true; do
  STATE=$(oci bastion bastion get --profile ${OCI_PROFILE} --bastion-id ${BASTION_ID} --query 'data."lifecycle-state"' --raw-output)
  echo "  State: ${STATE}"
  [[ "${STATE}" == "ACTIVE" ]] && break
  sleep 30
done
```

### Step 7: Create Node Pools

#### CPU Node Pool (for kube-system workloads)

```bash
# Get CPU image
CPU_IMAGE=$(oci compute image list \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --operating-system "Oracle Linux" \
  --operating-system-version "8" \
  --shape "VM.Standard.E5.Flex" \
  --query 'data[?contains("display-name", `OKE`)].id | [0]' --raw-output)

# Get AD
AD=$(oci iam availability-domain list \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --query "data[${GPU_AD_INDEX}].name" --raw-output)

# Create CPU node pool
oci ce node-pool create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --cluster-id ${CLUSTER_ID} \
  --name "cpu-pool" \
  --kubernetes-version ${K8S_VERSION} \
  --node-shape "VM.Standard.E5.Flex" \
  --node-shape-config '{"ocpus": 2, "memoryInGBs": 16}' \
  --node-image-id ${CPU_IMAGE} \
  --size 1 \
  --placement-configs "[{\"availabilityDomain\": \"${AD}\", \"subnetId\": \"${WORKER_SUBNET}\"}]"
```

#### GPU Node Pool

```bash
# Get GPU image (MUST be GPU-specific image)
GPU_IMAGE=$(oci compute image list \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --operating-system "Oracle Linux" \
  --operating-system-version "8" \
  --shape "${GPU_SHAPE}" \
  --query 'data[?contains("display-name", `GPU`)].id | [0]' --raw-output)

echo "GPU Image: ${GPU_IMAGE}"

# Create GPU node pool (WITHOUT cloud-init - see Gotchas section)
oci ce node-pool create \
  --profile ${OCI_PROFILE} \
  --compartment-id ${OCI_COMPARTMENT_ID} \
  --cluster-id ${CLUSTER_ID} \
  --name "gpu-pool" \
  --kubernetes-version ${K8S_VERSION} \
  --node-shape "${GPU_SHAPE}" \
  --node-image-id ${GPU_IMAGE} \
  --node-boot-volume-size-in-gbs ${GPU_BOOT_VOLUME_GB} \
  --size 1 \
  --placement-configs "[{\"availabilityDomain\": \"${AD}\", \"subnetId\": \"${WORKER_SUBNET}\"}]" \
  --initial-node-labels '[{"key": "app", "value": "gpu"}, {"key": "nvidia.com/gpu", "value": "true"}]'

echo "Waiting for GPU node pool to become ACTIVE..."
```

### Step 8: Configure kubectl Access

```bash
# Generate kubeconfig
oci ce cluster create-kubeconfig \
  --profile ${OCI_PROFILE} \
  --cluster-id ${CLUSTER_ID} \
  --file $HOME/.kube/config \
  --region ${OCI_REGION} \
  --token-version 2.0.0 \
  --kube-endpoint PRIVATE_ENDPOINT

# Get cluster private IP
PRIVATE_IP=$(oci ce cluster get \
  --profile ${OCI_PROFILE} \
  --cluster-id ${CLUSTER_ID} \
  --query 'data.endpoints."private-endpoint"' --raw-output | cut -d: -f1)

echo "Cluster Private IP: ${PRIVATE_IP}"
```

### Step 9: Create Bastion Session and SSH Tunnel

This is the critical step for accessing a private cluster.

```bash
# Create bastion session
SESSION_RESPONSE=$(oci bastion session create-port-forwarding \
  --profile ${OCI_PROFILE} \
  --bastion-id ${BASTION_ID} \
  --target-private-ip ${PRIVATE_IP} \
  --target-port 6443 \
  --session-ttl 10800 \
  --display-name "kubectl-tunnel" \
  --ssh-public-key-file ~/.ssh/id_rsa_oci.pub)

SESSION_ID=$(echo ${SESSION_RESPONSE} | jq -r '.data.id')
echo "Session ID: ${SESSION_ID}"

# Wait for session to become ACTIVE
while true; do
  STATE=$(oci bastion session get --profile ${OCI_PROFILE} --session-id ${SESSION_ID} --query 'data."lifecycle-state"' --raw-output)
  echo "  State: ${STATE}"
  [[ "${STATE}" == "ACTIVE" ]] && break
  sleep 10
done

# Get SSH command
SSH_CMD=$(oci bastion session get \
  --profile ${OCI_PROFILE} \
  --session-id ${SESSION_ID} \
  --query 'data."ssh-metadata".command' --raw-output)

echo "SSH Command template: ${SSH_CMD}"
```

**In a separate terminal**, start the SSH tunnel:

```bash
# Replace <privateKey> with your key path and <localPort> with 6443
ssh -i ~/.ssh/id_rsa_oci -N -L 6443:${PRIVATE_IP}:6443 \
  -o StrictHostKeyChecking=no \
  -o IdentitiesOnly=yes \
  -o ServerAliveInterval=30 \
  ${SESSION_ID}@host.bastion.${OCI_REGION}.oci.oraclecloud.com
```

**Update kubeconfig to use localhost:**

```bash
kubectl config set-cluster cluster-$(echo ${CLUSTER_ID} | cut -d. -f6) \
  --server=https://127.0.0.1:6443 \
  --insecure-skip-tls-verify=true

# Test connection
kubectl get nodes
```

### Step 10: Expand GPU Node Filesystem (CRITICAL)

> **Why this is needed**: OCI boot volumes have a FIXED ~47GB partition regardless of the volume size you request. Even with a 200GB boot volume, the OS only sees ~47GB until you manually expand it. The vLLM image alone is ~10GB, which will cause DiskPressure on unexpanded nodes.

#### Understanding the Expansion Process

OCI uses LVM (Logical Volume Manager) for the root filesystem. Expansion requires 4 steps **in this exact order**:

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `growpart /dev/sda 3` | Expands partition 3 to use the full disk **(CRITICAL - this must happen first!)** |
| 2 | `pvresize /dev/sda3` | Tells LVM the physical volume is now larger |
| 3 | `lvextend -l +100%FREE /dev/ocivolume/root` | Extends the logical volume to use the new space |
| 4 | `xfs_growfs /` | Grows the XFS filesystem to fill the logical volume |

**Important**: Steps 2-4 do NOTHING if step 1 hasn't run first! The partition must be expanded before LVM can use the space.

#### Option A: Use the Script (Recommended)

```bash
./entry_point.sh expand-disk
```

This runs all steps with proper verification.

#### Option B: Manual Expansion

```bash
# Get GPU node name
GPU_NODE=$(kubectl get nodes -l app=gpu -o jsonpath='{.items[0].metadata.name}')
echo "GPU Node: ${GPU_NODE}"

# Check current disk size
kubectl run check-size --rm -i --restart=Never --image=busybox:latest \
  --overrides="{\"spec\":{\"nodeName\":\"${GPU_NODE}\",\"tolerations\":[{\"operator\":\"Exists\"}],\"containers\":[{\"name\":\"c\",\"image\":\"busybox:latest\",\"command\":[\"sh\",\"-c\",\"chroot /host df -h /\"],\"securityContext\":{\"privileged\":true},\"volumeMounts\":[{\"name\":\"host\",\"mountPath\":\"/host\"}]}],\"volumes\":[{\"name\":\"host\",\"hostPath\":{\"path\":\"/\"}}]}}"

# Create expansion pod with ALL 4 STEPS
cat <<EOF | sed "s/\\\${GPU_NODE}/${GPU_NODE}/g" | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: expand-gpu-disk
spec:
  nodeName: \${GPU_NODE}
  hostPID: true
  tolerations:
  - operator: "Exists"
  priorityClassName: system-node-critical
  containers:
  - name: expand
    image: oraclelinux:8
    command: ["/bin/bash", "-c"]
    args:
    - |
      set -x
      echo "=== STEP 1: Expand partition with growpart ==="
      chroot /host bash -c '
        # Install growpart if needed
        yum install -y cloud-utils-growpart 2>/dev/null || true
        # This is the CRITICAL step - partition must be expanded first
        growpart /dev/sda 3
        fdisk -l /dev/sda | grep sda3
      '
      sleep 5

      echo "=== STEP 2: Resize LVM Physical Volume ==="
      chroot /host pvresize /dev/sda3
      chroot /host pvs /dev/sda3

      echo "=== STEP 3: Extend LVM Logical Volume ==="
      chroot /host lvextend -l +100%FREE /dev/ocivolume/root
      chroot /host lvs /dev/ocivolume/root

      echo "=== STEP 4: Grow XFS filesystem ==="
      chroot /host xfs_growfs /

      echo "=== FINAL SIZE ==="
      chroot /host df -h /
      echo "EXPANSION_COMPLETE"
    securityContext:
      privileged: true
    volumeMounts:
    - name: host
      mountPath: /host
  volumes:
  - name: host
    hostPath:
      path: /
  restartPolicy: Never
EOF

# Watch the logs (this takes 2-3 minutes)
kubectl logs -f expand-gpu-disk

# Wait for completion
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/expand-gpu-disk --timeout=300s

# Restart kubelet to update allocatable storage reporting
cat <<EOF | sed "s/\\\${GPU_NODE}/${GPU_NODE}/g" | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: restart-kubelet
spec:
  nodeName: \${GPU_NODE}
  hostPID: true
  tolerations:
  - operator: "Exists"
  containers:
  - name: restart
    image: busybox:latest
    command: ["/bin/sh", "-c", "chroot /host systemctl restart kubelet && sleep 10 && echo DONE"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: host
      mountPath: /host
  volumes:
  - name: host
    hostPath:
      path: /
  restartPolicy: Never
EOF

# Wait for kubelet restart
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/restart-kubelet --timeout=60s

# Cleanup
kubectl delete pod expand-gpu-disk restart-kubelet --force --grace-period=0

# Wait for node to be ready
kubectl wait --for=condition=Ready node/${GPU_NODE} --timeout=120s

# Wait for kubelet to report new size (takes ~60 seconds)
sleep 60

# Verify expansion (should show 180G+ total)
kubectl run verify-size --rm -i --restart=Never --image=busybox:latest \
  --overrides="{\"spec\":{\"nodeName\":\"${GPU_NODE}\",\"tolerations\":[{\"operator\":\"Exists\"}],\"containers\":[{\"name\":\"c\",\"image\":\"busybox:latest\",\"command\":[\"sh\",\"-c\",\"chroot /host df -h /\"],\"securityContext\":{\"privileged\":true},\"volumeMounts\":[{\"name\":\"host\",\"mountPath\":\"/host\"}]}],\"volumes\":[{\"name\":\"host\",\"hostPath\":{\"path\":\"/\"}}]}}"
```

#### Troubleshooting Expansion

If the filesystem didn't expand:

1. **Check the expansion pod logs** for errors in any step
2. **Verify partition was expanded**: `fdisk -l /dev/sda | grep sda3` should show ~200GB
3. **Verify LVM PV**: `pvs /dev/sda3` should show the new size
4. **Verify LVM LV**: `lvs /dev/ocivolume/root` should show the extended size
5. **Verify filesystem**: `df -h /` should show ~180GB total

If step 1 (growpart) didn't expand the partition, the disk geometry may not have been refreshed. Try:

```bash
# Force kernel to re-read partition table
chroot /host partprobe /dev/sda
chroot /host growpart /dev/sda 3
```

### Step 11: Install NVIDIA Device Plugin

```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml

# Wait for plugin to be ready
kubectl wait --for=condition=Ready pods -l name=nvidia-device-plugin-ds -n kube-system --timeout=300s

# Verify GPU is detected
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.nvidia\.com/gpu}{"\n"}{end}'
```

### Step 12: Apply Storage Classes

```bash
kubectl apply -f oci-block-storage-sc.yaml
```

### Step 13: Deploy vLLM Stack

```bash
# Add Helm repo
helm repo add vllm https://vllm-project.github.io/production-stack
helm repo update

# Deploy vLLM
helm upgrade -i --wait --timeout 15m \
  vllm vllm/vllm-stack \
  -f production_stack_specification.yaml

# Watch deployment progress
kubectl get pods -w
```

### Step 14: Fix Router Memory (Prevent OOMKill)

The default router memory (500Mi) is too low:

```bash
kubectl patch deployment vllm-deployment-router --type='json' -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "512Mi"},
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "1Gi"}
]'
```

### Step 15: Verify Deployment

```bash
# Check all pods are running
kubectl get pods

# Check model is loaded
kubectl port-forward svc/vllm-router-service 8080:80 &
curl http://localhost:8080/v1/models
pkill -f "port-forward.*8080"

# Test inference
kubectl port-forward svc/vllm-router-service 8080:80 &
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'
pkill -f "port-forward.*8080"
```

---

## Using the Automated Script

Once you have successfully completed the manual deployment at least once, you can use the automated script:

### Quick Start (After Manual Testing)

```bash
export OCI_PROFILE="your-profile"
export OCI_COMPARTMENT_ID="ocid1.compartment.oc1..xxx"
export OCI_REGION="us-ashburn-1"
export CLUSTER_NAME="vllm-production"
export GPU_AD_INDEX="1"  # Check GPU availability first!

# Step 1: Create infrastructure
./entry_point.sh setup

# Step 2: Create bastion session (shown in output)
# Step 3: Start SSH tunnel in separate terminal
# Step 4: Update kubeconfig to use localhost

# Step 5: Deploy vLLM
./entry_point.sh deploy-vllm
```

### Available Commands

| Command | Description |
|---------|-------------|
| `./entry_point.sh setup` | Create OKE cluster with GPU node pool |
| `./entry_point.sh deploy-vllm` | Deploy vLLM stack (after SSH tunnel is active) |
| `./entry_point.sh expand-disk` | Expand GPU node filesystem |
| `./entry_point.sh fix-router` | Increase router memory to 1Gi |
| `./entry_point.sh cleanup` | Delete all resources |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OCI_COMPARTMENT_ID` | Required | OCI compartment OCID |
| `OCI_PROFILE` | `DEFAULT` | OCI CLI profile |
| `OCI_REGION` | `us-ashburn-1` | OCI region |
| `CLUSTER_NAME` | `production-stack` | Cluster name |
| `GPU_SHAPE` | `VM.GPU.A10.1` | GPU shape |
| `GPU_BOOT_VOLUME_GB` | `200` | Boot volume size (GB) |
| `GPU_AD_INDEX` | `1` | Availability Domain index |
| `GPU_NODE_COUNT` | `1` | Number of GPU nodes |
| `PRIVATE_CLUSTER` | `true` | Use private endpoint |
| `BASTION_CLIENT_CIDR` | `0.0.0.0/0` | Allowed CIDR for bastion |

---

## Key Gotchas and Learnings

### 1. GPU Node Filesystem Expansion

**Problem**: OCI boot volumes have a ~47GB partition regardless of the boot volume size. Even with a 200GB boot volume, the OS only sees ~47GB.

**Solution**: Expand the filesystem AFTER the node joins the cluster using a privileged pod (see Step 10).

**Why not cloud-init?**: Using cloud-init with `oci-growfs` breaks OKE node registration (>20 minute timeout). The node never joins the cluster.

### 2. Disk Expansion Order Matters (CRITICAL)

**Problem**: `oci-growfs` can be slow, unreliable, or timeout during LVM operations. Even when it appears to succeed, the filesystem may not be expanded.

**Root Cause**: The LVM tools (`pvresize`, `lvextend`) **do nothing** if the underlying partition hasn't been expanded first. If `growpart` doesn't run (or fails), everything after it has no effect.

**Solution**: Always run all 4 steps explicitly and verify each one:

| Step | Command | What to verify |
|------|---------|----------------|
| 1 | `growpart /dev/sda 3` | `fdisk -l /dev/sda` shows ~200GB for sda3 |
| 2 | `pvresize /dev/sda3` | `pvs` shows new PV size |
| 3 | `lvextend -l +100%FREE /dev/ocivolume/root` | `lvs` shows new LV size |
| 4 | `xfs_growfs /` | `df -h /` shows ~180GB total |

**Key Insight**: Don't rely on `oci-growfs` alone. Always run `growpart` directly first to ensure the partition is expanded.

### 3. Router OOMKill

**Problem**: Default router memory (500Mi) causes OOMKill.

**Solution**: Patch to 1Gi after deployment (see Step 14).

### 4. GPU Availability Domain

**Problem**: A10 GPUs are not available in all ADs.

**Solution**: Check availability before deployment:

- `us-ashburn-1`: AD-2 and AD-3 (use `GPU_AD_INDEX=1` or `2`)
- `us-chicago-1`: AD-1 only (use `GPU_AD_INDEX=0`)

### 5. SSH Tunnel Stability

**Problem**: Bastion SSH tunnels can drop.

**Solution**: Use `ServerAliveInterval`:

```bash
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 ...
```

### 6. DiskPressure Before Image Pull

**Problem**: The vLLM container image is ~10GB and will cause DiskPressure if filesystem isn't expanded first.

**Solution**: Always expand the GPU node filesystem BEFORE deploying vLLM.

### 7. Expansion Pod Timing

**Problem**: When using automated scripts, the expansion pod may be deleted before the commands complete, leaving the filesystem unexpanded.

**Solution**:

- Stream pod logs to confirm each step completes
- Wait for the pod to reach "Succeeded" status before deleting
- Look for the "EXPANSION_COMPLETE" marker in the logs
- Verify the final filesystem size after expansion (should be >100GB)

### 8. Kubelet Refresh After Expansion

**Problem**: After expanding the filesystem, Kubernetes may still report the old allocatable storage.

**Solution**:

1. Restart kubelet after expansion: `systemctl restart kubelet`
2. Wait 60+ seconds for kubelet to recalculate allocatable storage
3. Verify with: `kubectl describe node <node> | grep ephemeral-storage`

---

## GPU Shapes Reference

| Shape | GPUs | GPU Type | Memory | Use Case |
|-------|------|----------|--------|----------|
| `VM.GPU.A10.1` | 1 | A10 | 24GB | 7B-13B models, GPT-OSS-20B (MoE) |
| `VM.GPU.A10.2` | 2 | A10 | 48GB | 20B+ models with tensor parallelism |
| `BM.GPU.A100-v2.8` | 8 | A100 80GB | 640GB | 70B models |
| `BM.GPU.H100.8` | 8 | H100 | 640GB | Large models, RDMA |

---

## Cost Estimates

| Resource | Hourly | Daily | Monthly |
|----------|--------|-------|---------|
| VM.GPU.A10.1 (1 GPU) | $2.00 | $48 | ~$1,440 |
| VM.GPU.A10.2 (2 GPUs) | $4.00 | $96 | ~$2,880 |
| CPU Node (2 OCPU) | $0.05 | $1.20 | ~$36 |
| Boot Volume (200GB) | - | $0.17 | ~$5 |
| **Total (1x A10)** | **~$2.07** | **~$50** | **~$1,500** |

---

## Cleanup

```bash
# Using script
./entry_point.sh cleanup

# Or manually
helm uninstall vllm
kubectl delete pvc --all
# Then delete OKE cluster, node pools, bastion, VCN via OCI Console or CLI
```

---

## Troubleshooting

### Pods stuck in Pending

```bash
kubectl describe pod <pod-name>
kubectl get events --sort-by='.lastTimestamp'
```

Common causes:

- DiskPressure: Expand filesystem (Step 10)
- Insufficient resources: Check node capacity
- GPU not detected: Verify NVIDIA device plugin

### DiskPressure on nodes

```bash
kubectl describe node <node-name> | grep -A5 "Conditions:"
```

Fix: Run filesystem expansion (Step 10)

### SSH tunnel drops

Create a new bastion session (they expire after TTL) and reconnect.

### Model loading fails

```bash
kubectl logs <vllm-pod-name>
```

Common causes:

- Insufficient GPU memory: Use smaller model or quantization
- Disk space: Expand filesystem
- HuggingFace token: Set `hf_token` in values if model requires authentication

---

## Support

- [vLLM Documentation](https://docs.vllm.ai/)
- [OCI OKE Documentation](https://docs.oracle.com/en-us/iaas/Content/ContEng/home.htm)
- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)
