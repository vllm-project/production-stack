#!/bin/bash
set -e

# Allow users to override the paths for the NVIDIA tools.
: "${NVIDIA_SMI_PATH:=nvidia-smi}"
: "${NVIDIA_CTK_PATH:=nvidia-ctk}"

# --- Debug and Environment Setup ---
echo "Current PATH: $PATH"
echo "Operating System: $(uname -a)"

# --- OS / arch detection ---
OS_KERNEL="$(uname -s)"
case "$OS_KERNEL" in
  Linux)  HOST_OS=linux ;;
  Darwin) HOST_OS=darwin ;;
  *)      echo "ERROR: unsupported OS: $OS_KERNEL" >&2; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64|amd64) HOST_ARCH=amd64 ;;
  arm64|aarch64) HOST_ARCH=arm64 ;;
  *) echo "ERROR: unsupported arch: $(uname -m)" >&2; exit 1 ;;
esac

# --- Helper Functions ---
# Check if minikube is installed AND is executable on this host (handles the
# common macOS pitfall of finding a Linux ELF binary on PATH).
minikube_exists() {
  command -v minikube >/dev/null 2>&1 && minikube version >/dev/null 2>&1
}

# Get the script directory to reference local scripts reliably.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Install Prerequisites ---
echo "Installing kubectl and helm..."
bash "$SCRIPT_DIR/install-kubectl.sh"
bash "$SCRIPT_DIR/install-helm.sh"

# Install minikube if it isn't already installed (or isn't executable on this host).
if minikube_exists; then
  echo "Minikube already installed."
else
  echo "Minikube not found or not executable on this host. Installing minikube for ${HOST_OS}-${HOST_ARCH}..."
  curl -fLO "https://github.com/kubernetes/minikube/releases/latest/download/minikube-${HOST_OS}-${HOST_ARCH}"
  sudo install "minikube-${HOST_OS}-${HOST_ARCH}" /usr/local/bin/minikube && rm "minikube-${HOST_OS}-${HOST_ARCH}"
fi

# --- Configure BPF (Linux only) ---
if [ -f /proc/sys/net/core/bpf_jit_harden ]; then
    echo "Configuring BPF: Setting net.core.bpf_jit_harden=0"
    echo "net.core.bpf_jit_harden=0" | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
else
    echo "BPF JIT hardening configuration not available, skipping..."
fi

calculate_safe_memory() {
  local floor_mb=2048
  local host_reserve_mb=2048

  local total_mb avail_mb
  if [[ "$HOST_OS" == "darwin" ]]; then
    # macOS: total via sysctl, treat "available" as ~60% of total (no
    # MemAvailable equivalent that maps cleanly to Docker Desktop's VM budget).
    local total_bytes
    total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    total_mb=$(( total_bytes / 1024 / 1024 ))
    avail_mb=$(( total_mb * 60 / 100 ))
  else
    # Linux: read /proc/meminfo.
    local total_kb avail_kb
    total_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
    avail_kb=$(awk  '/MemAvailable:/ {print $2}' /proc/meminfo)
    total_mb=$(( total_kb / 1024 ))
    avail_mb=$(( avail_kb > 0 ? avail_kb / 1024 : (total_mb * 60 / 100) ))
  fi

  # cgroup v2 limit if any (Linux only).
  local cg_raw cg_mb=0
  if [[ -r /sys/fs/cgroup/memory.max ]]; then
    cg_raw=$(cat /sys/fs/cgroup/memory.max)
    [[ "$cg_raw" != "max" ]] && cg_mb=$(( cg_raw / 1024 / 1024 ))
  fi

  local target=$(( avail_mb * 80 / 100 ))
  local total_cap=$(( total_mb * 90 / 100 ))
  (( target > total_cap )) && target=$total_cap

  local max_allowed=$(( total_mb - host_reserve_mb ))
  if (( cg_mb > 0 )); then
    local cg_cap=$(( cg_mb - host_reserve_mb ))
    (( cg_cap < max_allowed )) && max_allowed=$cg_cap
  fi

  # If the machine is too small, fail
  if (( max_allowed < floor_mb )); then
    echo "ERROR: Not enough RAM to auto-size (total=${total_mb}MB, allowed=${max_allowed}MB). Set MINIKUBE_MEM manually." >&2
    return 1
  fi

  (( target < floor_mb )) && target=$floor_mb
  (( target > max_allowed )) && target=$max_allowed

  echo "$target"
}

# --- NVIDIA GPU Setup ---
GPU_AVAILABLE=false
if command -v "$NVIDIA_SMI_PATH" >/dev/null 2>&1; then
    echo "NVIDIA GPU detected via nvidia-smi at: $(command -v "$NVIDIA_SMI_PATH")"
    if command -v "$NVIDIA_CTK_PATH" >/dev/null 2>&1; then
      echo "nvidia-ctk found at: $(command -v "$NVIDIA_CTK_PATH")"
      GPU_AVAILABLE=true
    else
      echo "nvidia-ctk not found. Please install the NVIDIA Container Toolkit to enable GPU support."
    fi
else
    echo "No NVIDIA GPU detected. Will start minikube without GPU support."
fi

if [[ -z "${MINIKUBE_MEM:-}" ]]; then
  MINIKUBE_MEM="$(calculate_safe_memory)"
fi

if [ "$GPU_AVAILABLE" = true ]; then
    # Configure Docker for GPU support.
    echo "Configuring Docker runtime for GPU support..."
    if sudo "$NVIDIA_CTK_PATH" runtime configure --runtime=docker; then
      # systemctl is Linux-only; on macOS Docker Desktop is restarted by the
      # user via the app, not via a service manager.
      if [[ "$HOST_OS" == "linux" ]] && command -v systemctl >/dev/null 2>&1; then
        echo "Restarting Docker to apply changes..."
        sudo systemctl restart docker
      else
        echo "Skipping 'systemctl restart docker' on ${HOST_OS}; please restart Docker Desktop manually if needed."
      fi
      echo "Docker runtime configured successfully."
    else
      echo "Error: Failed to configure Docker runtime using the NVIDIA Container Toolkit."
      exit 1
    fi

    # Start minikube with GPU support.
    echo "Starting minikube with GPU support..."
    minikube start --memory="${MINIKUBE_MEM}" --driver=docker --container-runtime=docker --gpus=all --force --addons=nvidia-device-plugin

    # Update kubeconfig context.
    echo "Updating kubeconfig context..."
    minikube update-context

    # Install the GPU Operator via Helm.
    echo "Adding NVIDIA helm repo and updating..."
    helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
    echo "Installing GPU Operator..."
    helm install --wait --generate-name -n gpu-operator --create-namespace nvidia/gpu-operator --version=v24.9.1
else
    # No GPU: Start minikube without GPU support.
    echo "Starting minikube without GPU support..."
    # Fix potential permission issues (Linux only — fs.protected_regular is a
    # Linux sysctl and macOS does not expose it).
    if [[ "$HOST_OS" == "linux" ]]; then
        sudo sysctl fs.protected_regular=0
    fi
    minikube start --memory="${MINIKUBE_MEM}" --driver=docker --force
fi

echo "Minikube cluster installation complete."
