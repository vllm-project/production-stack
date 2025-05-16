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

# Update crio config by creating (or editing) /etc/crio/crio.conf
sudo tee /etc/crio/crio.conf > /dev/null <<EOF
[crio.image]
pause_image="registry.k8s.io/pause:3.10"

[crio.runtime]
conmon_cgroup = "pod"
cgroup_manager = "systemd"
EOF

# Start CRI-O
sudo systemctl start crio.service

sudo swapoff -a
sudo modprobe br_netfilter
sudo sysctl -w net.ipv4.ip_forward=1

# Apply sysctl params without reboot
sudo sysctl --system

# Verify that net.ipv4.ip_forward is set to 1 with:
sudo sysctl net.ipv4.ip_forward
