#!/bin/bash

# Refer to https://github.com/cri-o/packaging/blob/main/README.md#distributions-using-deb-packages
# and
# https://github.com/cri-o/cri-o/blob/main/contrib/cni/README.md#configuration-directory
# for more information.

# Install the dependencies for adding repositories
sudo apt-get update
sudo apt-get install -y software-properties-common curl

export CRIO_VERSION=v1.32

# Add the CRI-O repository
curl -fsSL https://download.opensuse.org/repositories/isv:/cri-o:/stable:/$CRIO_VERSION/deb/Release.key |
    sudo gpg --dearmor -o /etc/apt/keyrings/cri-o-apt-keyring.gpg

echo "deb [signed-by=/etc/apt/keyrings/cri-o-apt-keyring.gpg] https://download.opensuse.org/repositories/isv:/cri-o:/stable:/$CRIO_VERSION/deb/ /" |
    sudo tee /etc/apt/sources.list.d/cri-o.list

# Install the packages
sudo apt-get update
sudo apt-get install -y cri-o

# Start CRI-O
sudo systemctl start crio.service

# Install CNI (container network interface) plugins
wget https://raw.githubusercontent.com/cri-o/cri-o/refs/heads/main/contrib/cni/11-crio-ipv4-bridge.conflist
sudo cp 11-crio-ipv4-bridge.conflist /etc/cni/net.d
