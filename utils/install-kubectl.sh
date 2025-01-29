#!/bin/bash

set -e

kubectl_exists() {
    command -v kubectl >/dev/null 2>&1
}

# If kubectl is already installed, exit

if kubectl_exists; then
    echo "kubectl is already installed"
    exit 0
fi

# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Test the installation
if kubectl_exists; then
    echo "kubectl installed successfully"
else
    echo "kubectl installation failed"
    exit 1
fi
