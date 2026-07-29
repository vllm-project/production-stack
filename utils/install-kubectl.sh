#!/bin/bash

set -e

KUBECTL_DIR="$HOME/.local/bin"
KUBECTL_PATH="$KUBECTL_DIR/kubectl"

# Detect host OS and architecture so we download the matching kubectl build.
# Without this the script always pulled the linux/amd64 binary, which on macOS
# installs an unexecutable Linux ELF (exec format error on later kubectl calls).
OS_KERNEL="$(uname -s)"
case "$OS_KERNEL" in
  Linux)  HOST_OS=linux ;;
  Darwin) HOST_OS=darwin ;;
  *)      echo "ERROR: unsupported OS: $OS_KERNEL" >&2; exit 1 ;;
esac

OS_ARCH="$(uname -m)"
case "$OS_ARCH" in
  x86_64 | amd64)   HOST_ARCH=amd64 ;;
  arm64 | aarch64)  HOST_ARCH=arm64 ;;
  *)                echo "ERROR: unsupported architecture: $OS_ARCH" >&2; exit 1 ;;
esac

# A kubectl on PATH only counts as installed if it actually runs on this host
# (a stale Linux binary on macOS is on PATH but cannot execute).
kubectl_exists() {
    command -v kubectl >/dev/null 2>&1 && kubectl version --client >/dev/null 2>&1
}

# If a working kubectl is already installed, exit
if kubectl_exists; then
    echo "kubectl is already installed"
    exit 0
fi

# Ensure the target directory exists
mkdir -p "$KUBECTL_DIR"

# Install kubectl for the detected platform. -f makes curl fail on HTTP errors
# instead of saving an error page as the binary.
curl -fLO "https://dl.k8s.io/release/$(curl -fL -s https://dl.k8s.io/release/stable.txt)/bin/${HOST_OS}/${HOST_ARCH}/kubectl"
chmod +x kubectl
mv kubectl "$KUBECTL_PATH"

# Add to PATH if not already included
if ! echo "$PATH" | grep -q "$KUBECTL_DIR"; then
    echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> ~/.bashrc
    echo "export PATH=\"$HOME/.local/bin:\$PATH\"" >> ~/.profile
    export PATH="$HOME/.local/bin:$PATH"
fi

# Test the installation
if kubectl_exists; then
    echo "kubectl installed successfully in $KUBECTL_PATH"
else
    echo "kubectl installation failed"
    exit 1
fi
