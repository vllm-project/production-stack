#!/bin/bash

set -e

KUBECTL_DIR="$HOME/.local/bin"
KUBECTL_PATH="$KUBECTL_DIR/kubectl"

kubectl_exists() {
    command -v kubectl >/dev/null 2>&1
}

# If kubectl is already installed, exit
if kubectl_exists; then
    echo "kubectl is already installed"
    exit 0
fi

# Ensure the target directory exists
mkdir -p "$KUBECTL_DIR"

# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
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
