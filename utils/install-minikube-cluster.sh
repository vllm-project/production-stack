#!/bin/bash
set -e

# Allow users to override the paths for the NVIDIA tools.
: "${NVIDIA_SMI_PATH:=nvidia-smi}"
: "${NVIDIA_CTK_PATH:=nvidia-ctk}"

# Debug: show current PATH and operating system details.
echo "Current PATH: $PATH"
echo "Operating System: $(uname -a)"

# Determine environment and update PATH if necessary.
if grep -qiE "(microsoft|wsl)" /proc/version 2>/dev/null; then
  echo "WSL environment detected. Appending common binary directories to PATH."
  export PATH="${PATH}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
else
  echo "Native Linux environment detected."
fi

# Ensure PATH is robust when running as root.
if [ "$EUID" -eq 0 ]; then
  echo "Running as root. Ensuring PATH includes common binary directories."
  export PATH="${PATH}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
fi

# Function to check if minikube exists.
# Allow users to override the paths for the NVIDIA tools.
: "${NVIDIA_SMI_PATH:=nvidia-smi}"
: "${NVIDIA_CTK_PATH:=nvidia-ctk}"

# Debug: show current PATH and operating system details.
echo "Current PATH: $PATH"
echo "Operating System: $(uname -a)"

# Determine environment and update PATH if necessary.
if grep -qiE "(microsoft|wsl)" /proc/version 2>/dev/null; then
  echo "WSL environment detected. Appending common binary directories to PATH."
  export PATH="${PATH}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
else
  echo "Native Linux environment detected."
fi

# Ensure PATH is robust when running as root.
if [ "$EUID" -eq 0 ]; then
  echo "Running as root. Ensuring PATH includes common binary directories."
  export PATH="${PATH}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
fi

# Function to check if minikube exists.
minikube_exists() {
  command -v minikube >/dev/null 2>&1
}

# Get script directory for relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Install kubectl and helm.
bash ./install-kubectl.sh
bash ./install-helm.sh

# Install minikube if it's not already installed.
# Install minikube if it's not already installed.
if minikube_exists; then
  echo "Minikube already installed."
  echo "Minikube already installed."
else
  echo "Minikube not found. Installing minikube..."
  echo "Minikube not found. Installing minikube..."
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

# --- GPU Setup Section ---

# Check for nvidia-smi.
if command -v "$NVIDIA_SMI_PATH" >/dev/null 2>&1; then
  echo "nvidia-smi found at: $(command -v "$NVIDIA_SMI_PATH")"
else
  echo "Error: nvidia-smi not found; no NVIDIA GPU detected."
  echo "Please ensure that the NVIDIA drivers are installed and nvidia-smi is in your PATH."
  exit 1
fi

# Check for nvidia-ctk.
if command -v "$NVIDIA_CTK_PATH" >/dev/null 2>&1; then
  echo "nvidia-ctk found at: $(command -v "$NVIDIA_CTK_PATH")"
# --- GPU Setup Section ---

# Check for nvidia-smi.
if command -v "$NVIDIA_SMI_PATH" >/dev/null 2>&1; then
  echo "nvidia-smi found at: $(command -v "$NVIDIA_SMI_PATH")"
else
  echo "Error: nvidia-smi not found; no NVIDIA GPU detected."
  echo "Please ensure that the NVIDIA drivers are installed and nvidia-smi is in your PATH."
  exit 1
fi

# Check for nvidia-ctk.
if command -v "$NVIDIA_CTK_PATH" >/dev/null 2>&1; then
  echo "nvidia-ctk found at: $(command -v "$NVIDIA_CTK_PATH")"
else
  echo "Error: nvidia-ctk not found."
  echo "Please install the NVIDIA Container Toolkit to enable GPU support."
  exit 1
fi

# Configure Docker runtime for GPU support.
echo "Configuring Docker runtime for GPU support..."
if sudo "$NVIDIA_CTK_PATH" runtime configure --runtime=docker; then
  echo "Restarting Docker to apply changes..."
  sudo systemctl restart docker
  echo "Docker runtime configured successfully."
else
  echo "Error: nvidia-ctk not found."
  echo "Please install the NVIDIA Container Toolkit to enable GPU support."
  echo "Error: Failed to configure Docker runtime using the NVIDIA Container Toolkit."
  exit 1
fi

# Configure Docker runtime for GPU support.
echo "Configuring Docker runtime for GPU support..."
if sudo "$NVIDIA_CTK_PATH" runtime configure --runtime=docker; then
  echo "Restarting Docker to apply changes..."
  sudo systemctl restart docker
  echo "Docker runtime configured successfully."
else
  echo "Error: Failed to configure Docker runtime using the NVIDIA Container Toolkit."
  exit 1
fi

# Start minikube with GPU support.
echo "Starting minikube with GPU support..."
sudo minikube start --driver docker --container-runtime docker --gpus all --force --addons=nvidia-device-plugin

# Update the kubeconfig context to point to the correct API endpoint.
echo "Updating kubeconfig context..."
sudo minikube update-context

# Restart the cluster to ensure proper configuration.
echo "Restarting the minikube cluster to ensure proper configuration..."
sudo minikube stop
echo "Starting minikube with GPU support..."
sudo minikube start --driver docker --container-runtime docker --gpus all --force --addons=nvidia-device-plugin

# Update the kubeconfig context to point to the correct API endpoint.
echo "Updating kubeconfig context..."
sudo minikube update-context

# Restart the cluster to ensure proper configuration.
echo "Restarting the minikube cluster to ensure proper configuration..."
sudo minikube stop
sudo minikube start --driver docker --container-runtime docker --gpus all --force --addons=nvidia-device-plugin

# Install the GPU Operator via helm.
echo "Adding NVIDIA helm repo and updating..."
# Install the GPU Operator via helm.
echo "Adding NVIDIA helm repo and updating..."
sudo helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && sudo helm repo update

echo "Installing GPU Operator..."
echo "Installing GPU Operator..."
sudo helm install --wait --generate-name \
    -n gpu-operator --create-namespace \
    nvidia/gpu-operator \
    --version=v24.9.1
