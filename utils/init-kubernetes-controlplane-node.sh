#!/bin/bash

# Refer to https://v1-32.docs.kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/
# for more information.
# This script will create a Kubernetes cluster using kubeadm.

# IMPORTANT: THIS STEP IS REQUIRED FOR CNI SETUP VIA CALICO

# Look for a line starting with "default via"
# For example: default via 10.128.0.1 dev ens5
ip route show

# Or get your network interface's ip address using the following command:
export K8S_NET_IP=$(ip addr show dev $(ip route show | awk '/^default/ {print $5}') | awk '/inet / {print $2}' | cut -d/ -f1)
echo "K8S_NET_IP=${K8S_NET_IP}"

# On one of your nodes which to become a control node, execute following command:
sudo kubeadm init \
    --cri-socket=unix:///var/run/crio/crio.sock \
    --apiserver-advertise-address=${K8S_NET_IP} \
    --pod-network-cidr=192.168.0.0/16

# The output will look like this:
# --------------------------------------------------------------------------------
# Your Kubernetes control-plane has initialized successfully!

# To start using your cluster, you need to run the following as a regular user:

#   mkdir -p $HOME/.kube
#   sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
#   sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Alternatively, if you are the root user, you can run:

#   export KUBECONFIG=/etc/kubernetes/admin.conf

# You should now deploy a pod network to the cluster.
# Run "kubectl apply -f [podnetwork].yaml" with one of the options listed at:
#   https://kubernetes.io/docs/concepts/cluster-administration/addons/

# Then you can join any number of worker nodes by running the following on each as root:

# kubeadm join <YOUR_CONTROL_PLANE_NODE_IP> --token <YOUR_GENERATED_TOKEN> \
#         --discovery-token-ca-cert-hash <YOUR_GENERATED_CA_CERT_HASH>
# --------------------------------------------------------------------------------

# Make sure to save the following command from your output:
# sudo kubeadm join <YOUR_CONTROL_PLANE_NODE_IP> --token <YOUR_GENERATED_TOKEN> \
#         --discovery-token-ca-cert-hash <YOUR_GENERATED_CA_CERT_HASH> --cri-socket=unix:///var/run/crio/crio.sock
