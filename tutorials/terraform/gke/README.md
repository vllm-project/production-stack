# 🚀 Deploying vLLM Production Stack on GKE With Terraform

This guide walks you through deploying a GPU-accelerated vLLM Production Stack on Google Kubernetes Engine (GKE) using Terraform. You'll create a complete infrastructure with specialized node pools for ML workloads and management services.

## 📋 Project Structure

```bash
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
2. A Google Cloud Platform account with [increased GPU Quota](https://stackoverflow.com/questions/45227064/how-to-request-gpu-quota-increase-in-google-cloud) (Note: GPU resources are limited by default and require an explicit quota increase request)
3. A service account with necessary permissions and credentials JSON file
4. The following tools installed on your local machine:
   - [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) - For interacting with Google Cloud services
   - [Terraform](https://developer.hashicorp.com/terraform/tutorials/gcp-get-started/install-cli) - For infrastructure as code deployment
   - [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl) - For managing the Kubernetes cluster
   - [Helm](https://helm.sh/docs/intro/install/) - For deploying the vLLM stack

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
   - Note: Node taints are Kubernetes features that "mark" nodes to repel pods that don't explicitly tolerate the taint

2. **Management Node Pool**:
   - E2-standard-4 instances (4 vCPUs, 16GB memory)
   - Designed for router and management services
   - Cost-effective for non-GPU workloads

### vLLM Stack

The deployment includes:

- NVIDIA Device Plugin for GPU support (enables Kubernetes to recognize and allocate GPUs)
- vLLM stack with OpenAI-compatible API endpoints (provides a familiar interface for LLM inference)
- Integrated with GKE ingress for external access

## 🎮 GPU and Model Selection

### Selecting GPU Types

When deploying your vLLM stack, you can customize the GPU types used for inference by modifying the `gke-infrastructure/variables.tf` file

```terraform
variable "gpu_machine_type" {
  description = "gpu node pool machine type"
  type = string
  default = "g2-standard-8" # (8vpu, 32GB mem)
}

variable "gpu_accelerator_type" {
  description = "gpu node pool gpu type"
  type = string
  default = "nvidia-l4"
}
```

You can adjust both the machine type and accelerator specifications to match your performance and budget requirements.

### 🖥️ Available Machine Types and GPU Combinations in GCP

#### 🚀 N1 Series Machines (Previous Generation)

| Machine Type | vCPUs | Memory (GB) | Compatible GPUs | Max GPUs |
|-------------|--------|-------------|-----------------|----------|
| n1-standard-2 | 2 | 7.5 | nvidia-tesla-t4 | 1 |
| n1-standard-4 | 4 | 15 | nvidia-tesla-t4, nvidia-tesla-p4 | 1 |
| n1-standard-8 | 8 | 30 | nvidia-tesla-t4, nvidia-tesla-p4, nvidia-tesla-v100 | 1 |
| n1-standard-16 | 16 | 60 | nvidia-tesla-t4, nvidia-tesla-p4, nvidia-tesla-v100 | 2 |
| n1-standard-32 | 32 | 120 | nvidia-tesla-t4, nvidia-tesla-p4, nvidia-tesla-v100 | 4 |

#### 🎯 G2 Series Machines (Latest Generation)

| Machine Type | vCPUs | Memory (GB) | Compatible GPUs | Max GPUs |
|-------------|--------|-------------|-----------------|----------|
| g2-standard-4 | 4 | 16 | nvidia-l4 | 1 |
| g2-standard-8 | 8 | 32 | nvidia-l4 | 1 |
| g2-standard-12 | 12 | 48 | nvidia-l4 | 2 |
| g2-standard-16 | 16 | 64 | nvidia-l4 | 2 |
| g2-standard-24 | 24 | 96 | nvidia-l4 | 4 |
| g2-standard-32 | 32 | 128 | nvidia-l4 | 4 |
| g2-standard-48 | 48 | 192 | nvidia-l4 | 6 |
| g2-standard-96 | 96 | 384 | nvidia-l4 | 8 |

### 🎮 GPU Specifications

| GPU Type | Memory | Best For | Relative Cost |
|----------|---------|----------|---------------|
| nvidia-tesla-t4 | 16 GB | ML inference, small-scale training | $ |
| nvidia-tesla-p4 | 8 GB | ML inference | $ |
| nvidia-tesla-v100 | 32 GB | Large-scale ML training | $$$ |
| nvidia-l4 | 24 GB | Latest gen for ML/AI workloads | $$ |

#### ⚠️ Note

- GPU availability varies by region and zone
- G2 machines are optimized for the latest NVIDIA L4 GPUs
- N1 machines are more flexible with GPU options but are previous generation
- Pricing varies significantly based on configuration and region
- More information -> [here](https://cloud.google.com/compute/docs/gpus?hl=en)

### Model Deployment Configuration

To specify which model to deploy, edit the `production_stack_specification.yaml` file
Please refer to this [production-stack's guide](https://github.com/vllm-project/production-stack/blob/main/tutorials/02-basic-vllm-config.md) for more information

## 🔧 Deployment Steps

### Option 1: Using the Makefile (Recommended)

The included Makefile automates the entire deployment process with the following commands:

```bash
# Deploy everything (infrastructure and vLLM stack)
make create
# This command provisions the GKE cluster, node pools, and deploys the vLLM stack in one step

# Deploy just the GKE infrastructure
make create-gke-infra
# This command creates only the GKE cluster and node pools without deploying vLLM

# Deploy just the vLLM stack on existing infrastructure
make create-helm-chart
# This command deploys the vLLM stack to an existing GKE cluster

# Clean up the vLLM stack only
make clean
# This command removes the vLLM stack but keeps the GKE infrastructure

# Clean up everything (complete removal)
make fclean
# This command removes both the vLLM stack and the entire GKE infrastructure
```

### Option 2: Manual Deployment

#### 1. Set up GKE Infrastructure

```bash
cd gke-infrastructure
terraform init     # Initialize Terraform and download required providers
terraform apply    # Review the plan and create the GKE infrastructure
```

#### 2. Connect to the Cluster

```bash
gcloud container clusters get-credentials production-stack --region=us-central1-a
# This command configures kubectl to use your newly created GKE cluster
# It adds an entry to your ~/.kube/config file
```

#### 3. Deploy vLLM Stack

```bash
cd ../production-stack
terraform init     # Initialize Terraform for the vLLM deployment
terraform apply    # Deploy the vLLM stack onto the GKE cluster
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

Once deployed, you can test your vLLM endpoint with these commands:

### 1. Get the external IP address

```bash
kubectl port-forward svc/vllm-router-service 30080:80
# This command creates a local port forwarding from port 30080 on your machine to port 80 on the vLLM router service
# This allows you to access the service as if it were running locally
```

### 2. Test model availability

```bash
curl -o- http://localhost:30080/v1/models | jq .
# This command checks which models are available through the vLLM API endpoint
# The jq tool formats the JSON response for better readability
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

### 3. Run inference

```bash
curl -X POST http://localhost:30080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "facebook/opt-125m",
    "prompt": "Once upon a time,",
    "max_tokens": 10
  }' | jq .
# This command sends a text completion request to the vLLM API endpoint
# It asks the model to generate 10 tokens following the prompt "Once upon a time,"
# The response is formatted using jq
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

## Observability dashboard

<p align="center">
  <img src="https://github.com/user-attachments/assets/05766673-c449-4094-bdc8-dea6ac28cb79" alt="Grafana dashboard to monitor the deployment" width="80%"/>
</p>

### Deploy the observability stack

The observability stack is based on [kube-prom-stack](https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/README.md).

After installing, the dashboard can be accessed through the service `service/kube-prom-stack-grafana` in the `monitoring` namespace.

### Access the Grafana & Prometheus dashboard

Forward the Grafana dashboard port to the local node-port

```bash
kubectl --namespace monitoring port-forward svc/kube-prom-stack-grafana 3000:80 --address 0.0.0.0
```

Forward the Prometheus dashboard

```bash
kubectl --namespace monitoring port-forward prometheus-kube-prom-stack-kube-prome-prometheus-0 9090:9090
```

Open the webpage at `http://<IP of your node>:3000` to access the Grafana web page. The default user name is `admin` and the password can be configured in `values.yaml` (default is `prom-operator`).

Import the dashboard using the `vllm-dashboard.json` in this folder.

### Use Prometheus Adapter to export vLLM metrics

The vLLM router can export metrics to Prometheus using the [Prometheus Adapter](https://github.com/prometheus-community/helm-charts/tree/main/charts/prometheus-adapter).
When running the `install.sh` script, the Prometheus Adapter will be installed and configured to export the vLLM metrics.

We provide a minimal example of how to use the Prometheus Adapter to export vLLM metrics. See [prom-adapter.yaml](prom-adapter.yaml) for more details.

The exported metrics can be used for different purposes, such as horizontal scaling of the vLLM deployments.

To verify the metrics are being exported, you can use the following command:

```bash
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1/namespaces/default/metrics | jq | grep vllm_num_requests_waiting -C 10
```

You should see something like the following:

```json
    {
      "name": "namespaces/vllm_num_requests_waiting",
      "singularName": "",
      "namespaced": false,
      "kind": "MetricValueList",
      "verbs": [
        "get"
      ]
    }
```

The following command will show the current value of the metric:

```bash
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1/namespaces/default/metrics/vllm_num_requests_waiting | jq
```

The output should look like the following:

```json
{
  "kind": "MetricValueList",
  "apiVersion": "custom.metrics.k8s.io/v1beta1",
  "metadata": {},
  "items": [
    {
      "describedObject": {
        "kind": "Namespace",
        "name": "default",
        "apiVersion": "/v1"
      },
      "metricName": "vllm_num_requests_waiting",
      "timestamp": "2025-03-02T01:56:01Z",
      "value": "0",
      "selector": null
    }
  ]
}
```

## 🧹 Cleanup

To avoid incurring charges when you're done:

```bash
# Using make (recommended)
make fclean
# This command removes all resources created during the deployment

# Or manually
cd production-stack
terraform destroy    # Remove the vLLM stack first
# This command removes all Helm releases and Kubernetes resources

cd ../gke-infrastructure
terraform destroy    # Then remove the GKE infrastructure
# This command removes the GKE cluster and node pools
```

## 🔧 Troubleshooting

If you encounter issues, here are some helpful commands:

### 1. Check node status

```bash
kubectl get nodes
# This command shows all nodes in your cluster with their status
# The STATUS column should show "Ready" for properly functioning nodes
NAME                                                  STATUS   ROLES    AGE     VERSION
gke-production-stack-production-stack-025c54c6-6h6n   Ready    <none>   6m6s    v1.31.5-gke.1233000
gke-production-stack-production-stack-ceaca16d-0v7b   Ready    <none>   5m54s   v1.31.5-gke.1233000
```

### 2. Verify GPU detection

```bash
kubectl describe no gke-production-stack-production-stack-025c54c6-6h6n | grep gpu
# This command checks if GPUs are properly detected on a specific node
# The output should show GPU-related labels, taints, and resource allocations
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

### 3. Check pod status

```bash
kubectl get po -A
# This command shows all pods across all namespaces
# The STATUS column should show "Running" for properly functioning pods
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

### 4. View logs

```bash
kubectl logs -f vllm-opt125m-deployment-vllm-59b9f7b4f5-b7gpj
# This command shows the logs of a specific pod and follows (-f) new log entries
# This is useful for debugging issues with the vLLM deployment
INFO 03-08 20:42:31 __init__.py:207] Automatically detected platform cuda.
INFO 03-08 20:42:31 api_server.py:912] vLLM API server version 0.7.3
INFO 03-08 20:42:31 api_server.py:913] args: Namespace(subparser='serve', mode~~
```

### 5. Check helm releases

```bash
helm list
# Lists all Helm releases in the current namespace

helm install vllm vllm/vllm-stack -f production_stack_specification.yaml
# Manually installs the vLLM stack using a configuration file

helm uninstall vllm
# Removes the vLLM stack deployment
```

### 6. Useful kubectl commands

```bash
kubectl get po -A
# Lists all pods across all namespaces

kubectl get no
# Lists all nodes in the cluster

kubectl api-resources
# Shows all resource types available in the cluster

kubectl config delete-context $CONTEXT_NAME
# Removes a specific context from kubectl configuration
# Replace $CONTEXT_NAME with the actual context name

kubectl config delete-user $NAME
# Removes a specific user from kubectl configuration
# Replace $NAME with the actual user name

kubectl config delete-cluster $NAME
# Removes a specific cluster from kubectl configuration
# Replace $NAME with the actual cluster name
```

### 7. Additional debugging

```bash
# Check GPU utilization on nodes
kubectl describe nodes | grep nvidia.com/gpu

# Verify vLLM service is properly exposed
kubectl get svc -n default

# Check for events that might indicate issues
kubectl get events --sort-by=.metadata.creationTimestamp

# Inspect ConfigMaps for any configuration issues
kubectl get cm -n default
```

## ☁️ Cost Management

GPU instances can be expensive to run. Here are some tips to manage costs:

```bash
# Scale down when not in use
kubectl scale deployment vllm-opt125m-deployment-vllm --replicas=0

# Scale back up when needed
kubectl scale deployment vllm-opt125m-deployment-vllm --replicas=1

# Set up node auto-provisioning in GKE to automatically scale based on demand
# This can be configured in the cluster.tf file
```

## 📚 Additional Resources

- [vLLM Documentation](https://vllm.ai/)
- [GKE Documentation](https://cloud.google.com/kubernetes-engine/docs)
- [Terraform GCP Provider](https://registry.terraform.io/providers/hashicorp/google/latest/docs)
- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)
- [production-stack with EKS](https://github.com/vllm-project/production-stack/compare/main...0xThresh:vllm-production-stack:tutorial-terraform-eks)
