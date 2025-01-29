#!/bin/bash
set -e

minikube_exists() {
  command -v minikube >/dev/null 2>&1
}

# Install kubectl and helm
bash ./install-kubectl.sh
bash ./install-helm.sh

# Install minikube
if minikube_exists; then
  echo "Minikube already installed"
else
  curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
  sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64
fi

echo "net.core.bpf_jit_harden=0" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker

# Start cluster
sudo minikube start --driver docker --container-runtime docker --gpus all --force --addons=nvidia-device-plugin

# Install gpu-operator
sudo helm repo add nvidia https://helm.ngc.nvidia.com/nvidia \
    && sudo helm repo update

sudo helm install --wait --generate-name \
    -n gpu-operator --create-namespace \
    nvidia/gpu-operator \
    --version=v24.9.1
