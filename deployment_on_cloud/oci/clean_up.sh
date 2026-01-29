#!/usr/bin/env bash

set -euo pipefail

# This script is a standalone cleanup utility.
# For full cleanup including cluster deletion, use: ./entry_point.sh cleanup

CLUSTER_NAME="${CLUSTER_NAME:-production-stack}"

echo "Starting cleanup for cluster: ${CLUSTER_NAME}"

# Uninstall Helm release
if helm status vllm &>/dev/null; then
    echo "Uninstalling vLLM Helm release..."
    helm uninstall vllm
else
    echo "No Helm release found to uninstall."
fi

# Delete vLLM PVCs only (scoped by label to avoid affecting other applications)
if kubectl get pvc --all-namespaces -l app.kubernetes.io/instance=vllm -o name 2>/dev/null | grep -q .; then
    echo "Deleting vLLM PVCs..."
    kubectl delete pvc --all-namespaces -l app.kubernetes.io/instance=vllm
else
    echo "No vLLM PVCs found to delete."
fi

# Note: PVCs with ReclaimPolicy:Delete will automatically remove associated PVs.
# Only delete PVs that are labeled for vLLM if they exist
if kubectl get pv -l app.kubernetes.io/instance=vllm -o name 2>/dev/null | grep -q .; then
    echo "Deleting vLLM PVs..."
    kubectl delete pv -l app.kubernetes.io/instance=vllm
else
    echo "No vLLM PVs found to delete."
fi

# Delete custom resources
if kubectl get deployments,services,configmaps,secrets -l app.kubernetes.io/name=vllm --all-namespaces -o name 2>/dev/null | grep -q .; then
    echo "Deleting custom resources..."
    kubectl delete deployments,services,configmaps,secrets --all-namespaces -l app.kubernetes.io/name=vllm
else
    echo "No custom vLLM resources found to delete."
fi

echo ""
echo "Kubernetes resources cleaned up."
echo ""
echo "To delete the OKE cluster and all OCI resources, run:"
echo "  ./entry_point.sh cleanup"
