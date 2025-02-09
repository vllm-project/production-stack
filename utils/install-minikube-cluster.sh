#!/bin/bash
set -e

minikube_exists() {
  command -v minikube >/dev/null 2>&1
}

# Get script directory for relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install kubectl and helm
bash "$SCRIPT_DIR/install-kubectl.sh"
bash "$SCRIPT_DIR/install-helm.sh"

# Install minikube
if minikube_exists; then
  echo "Minikube already installed"
else
  curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
  sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64
fi

# Configure BPF if available
if [ -f /proc/sys/net/core/bpf_jit_harden ]; then
    echo "net.core.bpf_jit_harden=0" | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
else
    echo "BPF JIT hardening configuration not available, skipping..."
fi

# Check if NVIDIA GPU is available
if command -v nvidia-smi &> /dev/null; then
    # Install nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker

    # Start cluster with GPU support
    minikube start --driver docker --container-runtime docker --gpus all --force --addons=nvidia-device-plugin

    # Install gpu-operator
    sudo helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && sudo helm repo update
    sudo helm install --wait --generate-name \
        -n gpu-operator --create-namespace \
        nvidia/gpu-operator \
        --version=v24.9.1
else
    echo "No NVIDIA GPU detected, starting minikube without GPU support..."
    # Fix permission issues
    sudo sysctl fs.protected_regular=0
    # Start cluster without GPU
    minikube start --driver docker --force
fi
