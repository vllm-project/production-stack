#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-production-stack}"
AZURE_REGION="${AZURE_REGION:-southcentralus}"
CLUSTER_NAME="${CLUSTER_NAME:-production-stack}"
USER_NAME="${USER_NAME:-azureuser}"

GPU_NODE_POOL_NAME="${GPU_NODE_POOL_NAME:-gpunodes}"
GPU_NODE_COUNT="${GPU_NODE_COUNT:-1}"

# Find more GPU VM sizes: https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview#gpu-accelerated
GPU_VM_SIZE="${GPU_VM_SIZE:-Standard_NC48ads_A100_v4}"

function deploy_aks() {
    echo "Creating resource group: ${AZURE_RESOURCE_GROUP}"
    az group create \
        --name "${AZURE_RESOURCE_GROUP}" \
        --location "${AZURE_REGION}"

    echo "Creating AKS cluster: ${CLUSTER_NAME}"
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

    az aks get-credentials \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --name "${CLUSTER_NAME}" \
        --overwrite-existing
}

function add_nodepool() {
    echo "Adding GPU node pool: ${GPU_NODE_POOL_NAME}"
    az aks nodepool add \
        --name "${GPU_NODE_POOL_NAME}" \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --cluster-name "${CLUSTER_NAME}" \
        --node-count "${GPU_NODE_COUNT}" \
        --node-vm-size "${GPU_VM_SIZE}"
}

function install_nvidia_device_plugin() {
    kubectl apply -f "${SCRIPT_DIR}/nvidia-device-plugin-ds.yaml"
}

function deploy_vllm_stack() {
    helm repo add vllm https://vllm-project.github.io/production-stack
    helm repo update

    HELM_VALUES_FLAG=""
    if [ -n "${1:-}" ]; then
        HELM_VALUES_FLAG="-f $1"
    fi

    # shellcheck disable=SC2086
    helm upgrade -i \
        --wait \
        vllm \
        vllm/vllm-stack ${HELM_VALUES_FLAG}
}

PARAM="${1:-err}"
case $PARAM in
setup)
    deploy_aks
    add_nodepool
    install_nvidia_device_plugin
    deploy_vllm_stack "${2:-}"
    ;;
cleanup)
    echo "Deleting the resource group: ${AZURE_RESOURCE_GROUP}"
    az group delete \
        --name "${AZURE_RESOURCE_GROUP}" \
        --yes \
        --no-wait
    ;;
*)
    echo "Usage: $0 <setup|cleanup> [HELM_VALUES_FILE]"
    exit 1
    ;;
esac
