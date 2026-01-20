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
echo "Uninstalling vLLM Helm release..."
helm uninstall vllm 2>/dev/null || echo "No Helm release found"

# Delete all PVCs
echo "Deleting PVCs..."
kubectl delete pvc --all 2>/dev/null || echo "No PVCs found"

# Delete all PVs
echo "Deleting PVs..."
kubectl delete pv --all 2>/dev/null || echo "No PVs found"

# Delete custom resources
echo "Deleting custom resources..."
kubectl delete deployments,services,configmaps,secrets -l app.kubernetes.io/name=vllm --all 2>/dev/null || true

echo ""
echo "Kubernetes resources cleaned up."
echo ""
echo "To delete the OKE cluster and all OCI resources, run:"
echo "  ./entry_point.sh cleanup"
