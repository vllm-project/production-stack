# Deploying vLLM production-stack on Azure AKS

This guide walks you through the script that sets up a vLLM production-stack on top of AKS on Azure. It includes creating an Azure resource group, an AKS cluster and deploying a production AI inference stack using Helm.

## Installing Prerequisites

Before running this setup, ensure you have:

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [Kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)
- [Helm](https://helm.sh/docs/intro/install/)

## TL;DR

### Set up

> [!CAUTION]
> This script requires cloud resources and will incur costs. Please make sure all resources are shut down properly.

To run the service, go to the [deployment_on_cloud/azure/](deployment_on_cloud/azure/) folder and run the following command:

```bash
cd deployment_on_cloud/azure/
./entry_point.sh setup
```

### Clean up

To clean up the service, run the following command:

```bash
./entry_point.sh cleanup
```

## Step by Step Explanation

### Step 1: Deploy Azure AKS Cluster

#### 1.1: Define Variables

```bash
AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-production-stack}"
AZURE_REGION="${AZURE_REGION:-southcentralus}"
CLUSTER_NAME="${CLUSTER_NAME:-production-stack}"
USER_NAME="${USER_NAME:-azureuser}"
GPU_NODE_POOL_NAME="${GPU_NODE_POOL_NAME:-gpunodes}"
GPU_NODE_COUNT="${GPU_NODE_COUNT:-1}"
GPU_VM_SIZE="${GPU_VM_SIZE:-Standard_NC48ads_A100_v4}"
```

- `AZURE_RESOURCE_GROUP`: The name of the Azure resource group. The default value is `production-stack`.
- `AZURE_REGION`: The Azure location or region where the AKS cluster will be deployed. The default value is `southcentralus`.
- `CLUSTER_NAME`: The name of the AKS cluster. The default value is `production-stack`.
- `USER_NAME`: The username for the AKS cluster. The default value is `azureuser`.
- `GPU_NODE_POOL_NAME`: The name of the GPU node pool. The default value is `gpunodes`.
- `GPU_NODE_COUNT`: The number of GPU nodes in the GPU node pool. The default value is `1`.
- `GPU_VM_SIZE`: The SKU of the GPU VMs in the GPU node pool. The default value is `Standard_NC48ads_A100_v4`. You can find more GPU VM sizes [here](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview#gpu-accelerated).

#### 1.2: Create Resource Group

```bash
az group create \
    --name "${AZURE_RESOURCE_GROUP}" \
    --location "${AZURE_REGION}"
```

This command creates an Azure resource group. Azure resource group is like a Kubernetes namespace that holds related resources. To clean up all resources, you can simply delete the resource group.

#### 1.3: Create AKS Cluster

```bash
az aks create \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${CLUSTER_NAME}" \
    --enable-oidc-issuer \
    --enable-workload-identity \
    --enable-managed-identity \
    --node-count 1 \
    --location "${AZURE_REGION}" \
    --admin-username "${USER_NAME}" \
    --generate-ssh-keys \
    --os-sku Ubuntu
```

This command creates an AKS cluster.

#### 1.4: Download the Kubeconfig file for the AKS cluster

```bash
az aks get-credentials \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${CLUSTER_NAME}" \
    --overwrite-existing
```

This command downloads the kubeconfig file for the AKS cluster. The file is stored in `~/.kube/config`.

### Step 2: Add GPUs

#### 2.1: Add GPU Node Pool

```bash
az aks nodepool add \
    --name "${GPU_NODE_POOL_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --cluster-name "${CLUSTER_NAME}" \
    --node-count "${GPU_NODE_COUNT}" \
    --node-vm-size "${GPU_VM_SIZE}"
```

This command adds specified number of GPU nodes to the AKS cluster.

#### 2.2: Deploy NVIDIA Device Plugin

```bash
kubectl apply -f "${SCRIPT_DIR}/nvidia-device-plugin-ds.yaml"
```

This command deploys the NVIDIA device plugin to the AKS cluster. The NVIDIA device plugin allows Kubernetes to access the GPUs on the nodes.

### Step 3: Deploy the Application Using Helm

After the cluster is created, the next step is to deploy the vLLM application using Helm. The following commands enable the vllm-stack Helm repository.

```bash
helm repo add vllm https://vllm-project.github.io/production-stack
helm repo update
```

This command installs the vLLM stack using the specified YAML configuration file, which contains the settings for the deployment.

```bash
helm upgrade -i --wait \
    vllm vllm/vllm-stack -f "$SETUP_YAML"
```

### Step 4: Clean Up

Cleaning up the resources is as simple as deleting the resource group.

```bash
az group delete \
    --name "${AZURE_RESOURCE_GROUP}" \
    --yes \
    --no-wait
```

## Conclusion

This tutorial covered:

✅ Creating an AKS cluster for vLLM deployment.

✅ Deploying the vLLM application using Helm.

✅ Cleaning up resources after deployment.

Now your Azure AKS production stack is ready for large-scale AI model deployment! 🚀
