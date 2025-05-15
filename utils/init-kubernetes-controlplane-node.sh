#!/bin/bash

sudo swapoff -a
sudo modprobe br_netfilter
sudo sysctl -w net.ipv4.ip_forward=1

# Refer to https://v1-32.docs.kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/
# for more information.
# This script will create a Kubernetes cluster using kubeadm.

# On one of your nodes which to become a control node, execute following command:
sudo kubeadm init --cri-socket=unix:///var/run/crio/crio.sock

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
