#!/bin/bash

set -euo pipefail
trap cleanup_resources EXIT

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Function to print status messages
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to verify CRD creation
verify_crd() {
    local crd_name=$1
    print_status "Verifying CRD: $crd_name"
    if ! kubectl get crd "$crd_name" > /dev/null 2>&1; then
        print_error "Failed to verify CRD: $crd_name"
        exit 1
    fi
    print_status "CRD $crd_name verified successfully"
}

# Function to verify CR creation
verify_cr() {
    local kind=$1
    local name=$2
    print_status "Verifying CR: $kind/$name"
    if ! kubectl get "$kind" "$name" > /dev/null 2>&1; then
        print_error "Failed to verify CR: $kind/$name"
        exit 1
    fi
    print_status "CR $kind/$name verified successfully"
}

# Function to cleanup resources
cleanup_resources() {
    print_status "Cleaning up test resources"
    # Delete CRs
    print_status "Deleting CRs"
    kubectl delete vllmruntime --all || true
    kubectl delete cacheserver --all || true
    kubectl delete vllmrouter --all || true

    # Delete CRDs
    print_status "Deleting CRDs"
    kubectl delete crd vllmruntimes.production-stack.vllm.ai || true
    kubectl delete crd cacheservers.production-stack.vllm.ai || true
    kubectl delete crd vllmrouters.production-stack.vllm.ai || true
}

# Main script execution
print_status "Starting CRD and CR validation test"

# Apply CRDs
print_status "Applying CRDs from operator/config/crd/bases"
for crd in operator/config/crd/bases/*.yaml; do
    print_status "Applying CRD: $crd"
    kubectl apply -f "$crd"
done

# Verify CRDs
verify_crd "vllmruntimes.production-stack.vllm.ai"
verify_crd "cacheservers.production-stack.vllm.ai"
verify_crd "vllmrouters.production-stack.vllm.ai"

# Apply sample CRs
print_status "Applying sample CRs from operator/config/samples"
for cr in operator/config/samples/*.yaml; do
    if [[ "$cr" != *"kustomization.yaml" ]]; then
        print_status "Applying CR: $cr"
        kubectl apply -f "$cr"
    fi
done

# Verify CRs
verify_cr "vllmruntime" "vllmruntime-sample"
verify_cr "cacheserver" "cacheserver-sample"
verify_cr "vllmrouter" "vllmrouter-sample"

# Cleanup resources
cleanup_resources

print_status "All CRDs and CRs validated successfully!"
