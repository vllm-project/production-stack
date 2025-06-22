#!/bin/bash

set -e

# Optionally use .local as KIND_DIR="$HOME/.local/bin"
KIND_DIR="$HOME/bin"
KIND_PATH="$KIND_DIR/kind"

kind_exists() {
    command -v kind >/dev/null 2>&1
}

# If kubectl is already installed, exit
if kind_exists; then
    echo "kind is already installed"
    exit 0
fi

# Ensure the target directory exists
mkdir -p "$KIND_DIR"

# Install kubectl (from tutorial https://kind.sigs.k8s.io/docs/user/quick-start/)
[ $(uname -m) = x86_64 ] && curl -Lo kind https://kind.sigs.k8s.io/dl/v0.29.0/kind-linux-amd64
# For ARM64
[ $(uname -m) = aarch64 ] && curl -Lo kind https://kind.sigs.k8s.io/dl/v0.29.0/kind-linux-arm64
chmod +x kind
sudo mv kind "$KIND_PATH"

# Add to PATH if not already included
if ! echo "$PATH" | grep -q "$KIND_DIR"; then
    echo "Adding kind directory to PATH environment variable"
    echo "export PATH=\"$HOME/bin:\$PATH\"" >> ~/.bashrc
    echo "export PATH=\"$HOME/bin:\$PATH\"" >> ~/.profile
    export PATH="$HOME/bin:$PATH"
fi

# Test the installation
if kind_exists; then
    echo "kind installed successfully in $KIND_PATH"
else
    echo "kind installation failed"
    exit 1
fi