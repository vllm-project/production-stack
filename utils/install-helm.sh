#!/bin/bash

set -e

helm_exists() {
    which helm > /dev/null 2>&1
}

# Skip if already installed helm
if helm_exists; then
    echo "Helm is installed"
    exit 0
fi

# Install Helm
curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3
chmod 700 get_helm.sh
./get_helm.sh

# Test helm installation
if helm_exists; then
    echo "Helm is successfully installed"
else
    echo "Helm installation failed"
    exit 1
fi
