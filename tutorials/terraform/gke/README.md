# 🚀 Deploying vLLM Production Stack on GKE With Terraform

This guide walks you through deploying a GPU-accelerated vLLM Production Stack on Google Kubernetes Engine (GKE) using Terraform. You'll create a complete infrastructure with specialized node pools for ML workloads and management services.

## 📋 Project Structure

```
gke/
├── credentials.json           # GCP service account credentials
├── gke-infrastructure/        # GKE cluster Terraform configuration
│   ├── backend.tf
│   ├── cluster.tf             # Main cluster configuration
│   ├── node_pools.tf          # Node pool definitions
│   ├── outputs.tf             # Output variables
│   ├── providers.tf           # Provider configuration
│   └── variables.tf           # Input variables
├── Makefile                   # Automation for deployment
├── production-stack/          # vLLM stack configuration
│   ├── backend.tf
│   ├── helm.tf                # Helm chart configurations
│   ├── production_stack_specification.yaml
│   ├── providers.tf
│   └── variables.tf
└── README.md
```

## ✅ Prerequisites

Before you begin, ensure you have:

1. A Google Cloud Platform account with appropriate permissions
2. A Google Cloud Platform account with [increase GPU Quota](https://stackoverflow.com/questions/45227064/how-to-request-gpu-quota-increase-in-google-cloud)
3. A service account with necessary permissions and credentials JSON file
4. The following tools installed on your local machine:
   - [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
   - [Terraform](https://developer.hashicorp.com/terraform/tutorials/gcp-get-started/install-cli)
   - [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)
   - [Helm](https://helm.sh/docs/intro/install/)

## 🏗️ Deployment Components

### GKE Cluster

The deployment creates a GKE cluster with the following features:
- Regular release channel for stability
- Comprehensive logging and monitoring
- VPC-native networking
- Managed Prometheus integration
- Public endpoint access

### Node Pools

Two specialized node pools are provisioned:

1. **Primary GPU Node Pool**:
   - NVIDIA L4 GPU accelerated instances
   - G2-standard-8 machine type (8 vCPUs, 32GB memory)
   - GPU driver auto-installation
   - Node taints to ensure GPU workloads run only on these nodes

2. **Management Node Pool**:
   - E2-standard-4 instances (4 vCPUs, 16GB memory)
   - Designed for router and management services
   - Cost-effective for non-GPU workloads

### vLLM Stack

The deployment includes:
- NVIDIA Device Plugin for GPU support
- vLLM stack with OpenAI-compatible API endpoints
- Integrated with GKE ingress for external access

## 🔧 Deployment Steps

### Option 1: Using the Makefile (Recommended)

The included Makefile automates the entire deployment process:

```bash
# Deploy everything (infrastructure and vLLM stack)
make create

# Deploy just the GKE infrastructure
make create-gke-infra

# Deploy just the vLLM stack on existing infrastructure
make create-helm-chart

# Clean up the vLLM stack only
make clean

# Clean up everything (complete removal)
make fclean
```

### Option 2: Manual Deployment

#### 1. Set up GKE Infrastructure

```bash
cd gke-infrastructure
terraform init
terraform apply
```

#### 2. Connect to the Cluster

```bash
gcloud container clusters get-credentials production-stack --region=us-central1-a
```

#### 3. Deploy vLLM Stack

```bash
cd ../production-stack
terraform init
terraform apply
```

## 📊 Key Infrastructure Details

### Cluster Configuration (cluster.tf)

```terraform
resource "google_container_cluster" "primary" {
  name = var.cluster_name
  location = var.zone
  
  # Configured with:
  # - Regular release channel
  # - Comprehensive logging & monitoring
  # - Managed Prometheus
  # - VPC-native networking
  # - Public endpoint access
  # ...
}
```

### Node Pools (node_pools.tf)

```terraform
resource "google_container_node_pool" "primary_nodes" {
  # GPU-accelerated nodes with:
  # - NVIDIA L4 GPUs
  # - G2-standard-8 instances
  # - GPU taint configuration
  # ...
}

resource "google_container_node_pool" "mgmt_nodes" {
  # Management nodes with:
  # - E2-standard-4 instances
  # - Optimized for router and management workloads
  # ...
}
```

### Helm Charts (helm.tf)

```terraform
# NVIDIA Device Plugin
resource "helm_release" "nvidia_device_plugin" {
  name = "nvidia-device-plugin"
  repository = "https://nvidia.github.io/k8s-device-plugin"
  # ...
}

# vLLM Stack
resource "helm_release" "vllm" {
  name = "vllm"
  repository = "https://vllm-project.github.io/production-stack"
  # ...
}
```

## 🔍 Testing Your Deployment

Once deployed, you can test your vLLM endpoint:

1. Get the external IP address:

```bash
kubectl port-forward svc/vllm-router-service 30080:80
```

2. Test model availability:

```bash
curl -o- http://localhost:30080/v1/models | jq .
{
  "object": "list",
  "data": [
    {
      "id": "facebook/opt-125m",
      "object": "model",
      "created": 1741495827,
      "owned_by": "vllm",
      "root": null
    }
  ]
}
```

3. Run inference:

```bash
curl -X POST http://localhost:30080/v1/completions \
   -H "Content-Type: application/json" \
   -d '{
     "model": "facebook/opt-125m",
     "prompt": "Once upon a time,",
     "max_tokens": 10
   }' | jq .
{
  "id": "cmpl-72c009ae91964badb0c09b96bedb399d",
  "object": "text_completion",
  "created": 1741495870,
  "model": "facebook/opt-125m",
  "choices": [
    {
      "index": 0,
      "text": " Joel Schumaker ran Anton Harriman and",
      "logprobs": null,
      "finish_reason": "length",
      "stop_reason": null,
      "prompt_logprobs": null
    }
  ],
  "usage": {
    "prompt_tokens": 6,
    "total_tokens": 16,
    "completion_tokens": 10,
    "prompt_tokens_details": null
  }
}
```

## 🧹 Cleanup

To avoid incurring charges when you're done:

```bash
# Using make (recommended)
make fclean

# Or manually
cd production-stack
terraform destroy

cd ../gke-infrastructure
terraform destroy
```

## 🔧 Troubleshooting

If you encounter issues:

1. Check node status:
```bash
kubectl get nodes   
NAME                                                  STATUS   ROLES    AGE     VERSION
gke-production-stack-production-stack-025c54c6-6h6n   Ready    <none>   6m6s    v1.31.5-gke.1233000
gke-production-stack-production-stack-ceaca16d-0v7b   Ready    <none>   5m54s   v1.31.5-gke.1233000
```

2. Verify GPU detection:
```bash
kubectl describe no gke-production-stack-production-stack-025c54c6-6h6n | grep gpu
                    cloud.google.com/gke-gpu=true
                    cloud.google.com/gke-gpu-driver-version=latest
                    nvidia.com/gpu=present
                    node.gke.io/last-applied-node-taints: nvidia.com/gpu=present:NoSchedule
Taints:             nvidia.com/gpu=present:NoSchedule
  nvidia.com/gpu:     1
  nvidia.com/gpu:     1
  kube-system                 nvidia-gpu-device-plugin-small-cos-h44rj                          150m (1%)     1 (12%)     80Mi (0%)        80Mi (0%)      10m
  nvidia.com/gpu     1                 1
```

3. Check pod status:
```bash
kubectl get po -A
NAMESPACE         NAME                                                             READY   STATUS    RESTARTS   AGE
default           vllm-deployment-router-6fdf446f64-vpws2                          1/1     Running   0          10m
default           vllm-opt125m-deployment-vllm-59b9f7b4f5-b7gpj                    1/1     Running   0          10m
gke-managed-cim   kube-state-metrics-0                                             2/2     Running   0          16m
gmp-system        collector-hg256                                                  2/2     Running   0          11m
gmp-system        collector-x68wc                                                  2/2     Running   0          11m
gmp-system        gmp-operator-798bc757b4-4pr9c                                    1/1     Running   0          17m
kube-system       event-exporter-gke-5c5b457d58-9rc9r                              2/2     Running   0          17m
kube-system       fluentbit-gke-6cvrj                                              3/3     Running   0          11m
kube-system       fluentbit-gke-vhln4                                              3/3     Running   0          11m
kube-system       gke-metrics-agent-pv7qc                                          3/3     Running   0          11m
kube-system       gke-metrics-agent-wj9rj                                          3/3     Running   0          11m
kube-system       konnectivity-agent-676cff855d-m8jsw                              2/2     Running   0          10m
kube-system       konnectivity-agent-676cff855d-xj2g8                              2/2     Running   0          17m
kube-system       konnectivity-agent-autoscaler-cc5bd5684-2749t                    1/1     Running   0          17m
kube-system       kube-dns-75d9d64858-htczb                                        5/5     Running   0          10m
kube-system       kube-dns-75d9d64858-zdfhj                                        5/5     Running   0          17m
kube-system       kube-dns-autoscaler-6ffdbff798-l47bh                             1/1     Running   0          16m
kube-system       kube-proxy-gke-production-stack-production-stack-025c54c6-6h6n   1/1     Running   0          11m
kube-system       kube-proxy-gke-production-stack-production-stack-ceaca16d-0v7b   1/1     Running   0          11m
kube-system       l7-default-backend-87b58b54c-lrf6n                               1/1     Running   0          16m
kube-system       maintenance-handler-tswrp                                        1/1     Running   0          11m
kube-system       metrics-server-v1.31.0-769c5b4896-bpt9c                          1/1     Running   0          16m
kube-system       nvidia-gpu-device-plugin-small-cos-h44rj                         2/2     Running   0          11m
kube-system       pdcsi-node-86cjg                                                 2/2     Running   0          11m
kube-system       pdcsi-node-jpk2c                                                 2/2     Running   0          11m
```

4. View logs:
```bash
kubectl logs -f vllm-opt125m-deployment-vllm-59b9f7b4f5-b7gpj
INFO 03-08 20:42:31 __init__.py:207] Automatically detected platform cuda.
INFO 03-08 20:42:31 api_server.py:912] vLLM API server version 0.7.3
INFO 03-08 20:42:31 api_server.py:913] args: Namespace(subparser='serve', mode~~
```

5. Check helm state:
```bash
helm install vllm vllm/vllm-stack -f production_stack_specification.yaml
helm uninstall vllm
```

6. Useful kubectl command 
```bash
kubectl get po -A
kubectl get no
kubectl api-resources
kubectl config delete-context $CONTEXT_NAME
kubectl config delete-user $NAME
kubectl config delete-cluster $NAME
```

## 📚 Additional Resources

- [vLLM Documentation](https://vllm.ai/)
- [GKE Documentation](https://cloud.google.com/kubernetes-engine/docs)
- [Terraform GCP Provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)
- [production-stack with EKS](https://github.com/vllm-project/production-stack/compare/main...0xThresh:vllm-production-stack:tutorial-terraform-eks)

