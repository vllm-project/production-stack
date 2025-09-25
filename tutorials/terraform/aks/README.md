# 🚀 Deploying vLLM Production Stack on Azure Kubernetes Service With Terraform

This guide walks you through deploying a GPU-accelerated vLLM Production Stack on Azure Kubernetes Service using Terraform. You'll create a complete infrastructure with specialized node pools for ML workloads and management services.

## 📋 Project Structure

```bash
./
├── azurek8s                   # Azure Kubernetes config file
├── azure-infrastructure/      # Azure cluster Terraform configuration
│   ├── cluster.tf             # Main cluster configuration
│   ├── create-config.tf       # Kubeconfig generation
│   ├── outputs.tf             # Output variables
│   ├── provider.tf            # Provider configuration
│   ├── ssh.tf                 # SSH key management
│   └── variables.tf           # Input variables
├── Makefile                   # Automation for deployment
├── production-stack/          # vLLM stack configuration
│   ├── helm.tf                # Helm chart configurations
│   ├── provider.tf            # Provider configuration
│   └── variables.tf           # Input variables
├── production_stack_specification.yaml
└── README.md
```

## ✅ Prerequisites

Before you begin, ensure you have:

1. An Azure account with appropriate permissions
2. An Azure subscription with [increased GPU Quota](https://docs.microsoft.com/en-us/azure/azure-resource-manager/management/azure-subscription-service-limits) (Note: GPU resources are limited by default and require an explicit quota increase request)
3. The following tools installed on your local machine:
   - [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) - For interacting with Azure services
   - [Terraform](https://developer.hashicorp.com/terraform/tutorials/azure-get-started/install-cli) - For infrastructure as code deployment
   - [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl) - For managing the Kubernetes cluster
   - [Helm](https://helm.sh/docs/intro/install/) - For deploying the vLLM stack

## 🏗️ Deployment Components

### Azure Cluster

The deployment creates an Azure cluster with the following features:

- System-assigned managed identity
- Kubenet networking plugin
- Standard load balancer
- Linux admin user with SSH key authentication
- Resource group with randomized naming

### Node Pools

Two specialized node pools are provisioned:

1. **Default Node Pool (agentpool)**:
   - Standard_D4_v4 instances (4 vCPUs, 16GB memory)
   - Designed for management and general workloads
   - Cost-effective for non-GPU workloads

2. **GPU Node Pool (gpupool)**:
   - Standard_NC4as_T4_v3 instances with NVIDIA T4 GPU
   - GPU driver auto-installation via NVIDIA GPU Operator
   - Node labels and taints to ensure GPU workloads run only on these nodes
   - Note: Node taints are Kubernetes features that "mark" nodes to repel pods that don't explicitly tolerate the taint

### vLLM Stack

The deployment includes:

- NVIDIA GPU Operator for GPU support (enables Kubernetes to recognize and allocate GPUs)
- vLLM stack with OpenAI-compatible API endpoints (provides a familiar interface for LLM inference)
- Prometheus monitoring stack for observability
- Prometheus adapter for custom metrics

## 🎮 GPU and Model Selection

### Selecting GPU Types

When deploying your vLLM stack, you can customize the GPU types used for inference by modifying the `azure-infrastructure/cluster.tf` file:

```terraform
resource "azurerm_kubernetes_cluster_node_pool" "gpu_node_pool" {
  name = "gpupool"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.k8s.id
  vm_size = "standard_nc4as_t4_v3"  # Change this for different GPU types
  node_count = 1

  node_labels = {
    "nvidia.com/gpu" = "present"
  }

  node_taints = ["nvidia.com/gpu=present:NoSchedule"]
}
```

You can adjust the `vm_size` to match your performance and budget requirements.

### 🖥️ Available GPU-Enabled VM Sizes in Azure

#### 🚀 NC Series (NVIDIA Tesla T4)

| VM Size | vCPUs | Memory (GB) | GPUs | GPU Memory | Best For |
|---------|--------|-------------|------|------------|----------|
| Standard_NC4as_T4_v3 | 4 | 28 | 1 | 16 GB | Small inference workloads |
| Standard_NC8as_T4_v3 | 8 | 56 | 1 | 16 GB | Medium inference workloads |
| Standard_NC16as_T4_v3 | 16 | 110 | 1 | 16 GB | Large inference workloads |
| Standard_NC64as_T4_v3 | 64 | 440 | 4 | 64 GB | Multi-GPU inference |

#### 🎯 NCv3 Series (NVIDIA Tesla V100)

| VM Size | vCPUs | Memory (GB) | GPUs | GPU Memory | Best For |
|---------|--------|-------------|------|------------|----------|
| Standard_NC6s_v3 | 6 | 112 | 1 | 32 GB | Training and inference |
| Standard_NC12s_v3 | 12 | 224 | 2 | 64 GB | Multi-GPU training |
| Standard_NC24s_v3 | 24 | 448 | 4 | 128 GB | Large-scale training |

#### 🔥 Azure -ND- Series (NVIDIA A100)

| VM Size | vCPUs | Memory (GB) | GPUs | GPU Memory | Best For |
|---------|--------|-------------|------|------------|----------|
| Standard_ND96asr_v4 | 96 | 900 | 8 | 320 GB | Large-scale AI training |

### 🎮 GPU Specifications

| GPU Type | Memory | Best For | Relative Cost |
|----------|---------|----------|---------------|
| NVIDIA Tesla T4 | 16 GB | ML inference, small-scale training | $ |
| NVIDIA Tesla V100 | 32 GB | Large-scale ML training and inference | $$$ |
| NVIDIA A100 | 40/80 GB | Cutting-edge AI workloads | $$$$ |

#### ⚠️ Note

- GPU availability varies by Azure region
- NC T4 series are optimized for inference workloads
- NCv3 and -ND- series are better for training workloads
- Pricing varies significantly based on configuration and region
- More information → [Azure GPU VM sizes](https://docs.microsoft.com/en-us/azure/virtual-machines/sizes-gpu)

### Model Deployment Configuration

To specify which model to deploy, edit the `production_stack_specification.yaml` file.
Please refer to this [production-stack's guide](https://github.com/vllm-project/production-stack/blob/main/tutorials/02-basic-vllm-config.md) for more information.

## 🔧 Deployment Steps

### Option 1: Using the Makefile (Recommended)

The included Makefile automates the entire deployment process with the following commands:

```bash
# Deploy everything (infrastructure and vLLM stack)
make create
# This command provisions the Azure cluster, node pools, and deploys the vLLM stack in one step

# Deploy just the azure infrastructure
make create-azure-infra
# This command creates only the Azure cluster and node pools without deploying vLLM

# Deploy just the vLLM stack on existing infrastructure
make create-helm-chart
# This command deploys the vLLM stack to an existing Azure cluster

# Clean up the vLLM stack only
make clean
# This command removes the vLLM stack but keeps the Azure infrastructure

# Clean up everything (complete removal)
make fclean
# This command removes both the vLLM stack and the entire Azure infrastructure
```

### Option 2: Manual Deployment

#### 1. Azure Authentication

```bash
# Login to Azure
az login

# Set your subscription (if you have multiple)
az account set --subscription "your-subscription-id"
```

#### 2. Set up Azure Infrastructure

```bash
cd azure-infrastructure
terraform init     # Initialize Terraform and download required providers
terraform apply    # Review the plan and create the Azure infrastructure
```

#### 3. Connect to the Cluster

```bash
# The kubeconfig is automatically generated as 'azurek8s' file
export KUBECONFIG=./azurek8s
# This command configures kubectl to use your newly created Azure cluster
```

#### 4. Deploy vLLM Stack

```bash
cd ../production-stack
terraform init     # Initialize Terraform for the vLLM deployment
terraform apply    # Deploy the vLLM stack onto the Azure cluster
```

## 📊 Key Infrastructure Details

### Cluster Configuration (cluster.tf)

```terraform
resource "azurerm_kubernetes_cluster" "k8s" {
  location = azurerm_resource_group.rg.location
  name = random_pet.azurerm_kubernetes_cluster_name.id
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix = random_pet.azurerm_kubernetes_cluster_dns_prefix.id

  # Configured with:
  # - System-assigned managed identity
  # - Kubenet networking
  # - Standard load balancer
  # - Linux profile with SSH access
  # ...
}
```

### Node Pools (cluster.tf)

```terraform
# Default node pool for management workloads
resource "azurerm_kubernetes_cluster" "k8s" {
  default_node_pool {
    name = "agentpool"
    vm_size = "standard_d4_v4"
    node_count = var.node_count
  }
  # ...
}

# GPU node pool for ML workloads
resource "azurerm_kubernetes_cluster_node_pool" "gpu_node_pool" {
  name = "gpupool"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.k8s.id
  vm_size = "standard_nc4as_t4_v3"
  node_count = 1

  node_labels = {
    "nvidia.com/gpu" = "present"
  }

  node_taints = ["nvidia.com/gpu=present:NoSchedule"]
}
```

### Helm Charts (helm.tf)

```terraform
# NVIDIA GPU Operator
resource "helm_release" "gpu_operator" {
  name       = "gpu-operator"
  namespace  = "gpu-operator"
  repository = "https://helm.ngc.nvidia.com/nvidia"
  chart      = "gpu-operator"
  # ...
}

# vLLM Stack
resource "helm_release" "vllm" {
  name       = "vllm"
  repository = "https://vllm-project.github.io/production-stack"
  chart      = "vllm-stack"
  # ...
}

# Prometheus Monitoring Stack
resource "helm_release" "kube_prometheus_stack" {
  name             = "kube-prom-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  # ...
}
```

## 🚨 Important Notes

### Azure-Specific Considerations

1. **Resource Naming**: The deployment uses random naming for Azure resources to ensure uniqueness across your subscription.

2. **SSH Access**: An SSH key pair is automatically generated for cluster access. The public key is stored in Azure and can be retrieved via Terraform outputs.

3. **Networking**: The cluster uses Kubenet networking, which is suitable for most workloads. For advanced networking scenarios, consider switching to Azure CNI.

4. **GPU Quotas**: Ensure you have sufficient GPU quota in your target Azure region before deployment.

5. **Monitoring**: The deployment includes a complete Prometheus monitoring stack for observability of your ML workloads.

## 🔍 Testing Your Deployment

Once deployed, you can test your vLLM endpoint with these commands:

### 1. Get azure kubernetes service kubeconfig

```bash
export KUBECONFIG="azurek8s"
```

### 2. Get the external IP address

```bash
kubectl port-forward svc/vllm-router-service 30080:80
# This command creates a local port forwarding from port 30080 on your machine to port 80 on the vLLM router service
# This allows you to access the service as if it were running locally
```

### 3. Test model availability

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

### 4. Run inference

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
When running the [`install.sh`](../../../observability/install.sh) script, the Prometheus Adapter will be installed and configured to export the vLLM metrics.

We provide a minimal example of how to use the Prometheus Adapter to export vLLM metrics. See [prom-adapter.yaml](../../../observability/prom-adapter.yaml) for more details.

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

cd ../azure-infrastructure
terraform destroy    # Then remove the Azure infrastructure
# This command removes the Azure cluster and node pools
```

## ☁️ Cost Management

GPU instances can be expensive to run. Here are some tips to manage costs:

```bash
# Scale down when not in use
kubectl scale deployment vllm-opt125m-deployment-vllm --replicas=0

# Scale back up when needed
kubectl scale deployment vllm-opt125m-deployment-vllm --replicas=1

# Set up node auto-provisioning in Azure to automatically scale based on demand
# This can be configured in the cluster.tf file
```

## 📚 Additional Resources

- [vLLM Documentation](https://vllm.ai/)
- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)
