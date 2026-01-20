#!/usr/bin/env bash

set -euo pipefail

# This script is a standalone cleanup utility.
# For full cleanup including cluster deletion, use: ./entry_point.sh cleanup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"

OCI_COMPARTMENT_ID="${OCI_COMPARTMENT_ID:-}"
CLUSTER_NAME="${CLUSTER_NAME:-production-stack}"

if [[ -z "${OCI_COMPARTMENT_ID}" ]]; then
    echo "Error: OCI_COMPARTMENT_ID environment variable is required"
    exit 1
fi

echo "Starting cleanup for cluster: ${CLUSTER_NAME}"

# Uninstall Helm release
if helm status vllm &>/dev/null; then
    echo "Uninstalling vLLM Helm release..."
    helm uninstall vllm
else
    echo "No Helm release found to uninstall."
fi

# Delete all PVCs
if kubectl get pvc --all-namespaces -o name 2>/dev/null | grep -q .; then
    echo "Deleting PVCs..."
    kubectl delete pvc --all
else
    echo "No PVCs found to delete."
fi

# Delete all PVs
if kubectl get pv -o name 2>/dev/null | grep -q .; then
    echo "Deleting PVs..."
    kubectl delete pv --all
else
    echo "No PVs found to delete."
fi

# Delete custom resources
if kubectl get deployments,services,configmaps,secrets -l app.kubernetes.io/name=vllm --all-namespaces -o name 2>/dev/null | grep -q .; then
    echo "Deleting custom resources..."
    kubectl delete deployments,services,configmaps,secrets -l app.kubernetes.io/name=vllm --all
else
    echo "No custom vLLM resources found to delete."
fi

echo ""
echo "Kubernetes resources cleaned up."
echo ""
echo "To delete the OKE cluster and all OCI resources, run:"
echo "  ./entry_point.sh cleanup"
