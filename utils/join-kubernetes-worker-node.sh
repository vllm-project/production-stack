#!/bin/bash

# You got following output from previous control node initialization:

# --------------------------------------------------------------------------------
# Your Kubernetes control-plane has initialized successfully!
#
# ...
#
# Then you can join any number of worker nodes by running the following on each as root:
#
# kubeadm join <YOUR_CONTROL_PLANE_NODE_IP> --token <YOUR_GENERATED_TOKEN> \
#         --discovery-token-ca-cert-hash sha256:<YOUR_GENERATED_CA_CERT_HASH>
# --------------------------------------------------------------------------------

# Make sure to execute the following command on your worker node:
sudo kubeadm join <YOUR_CONTROL_PLANE_NODE_IP> --token <YOUR_GENERATED_TOKEN> \
         --discovery-token-ca-cert-hash sha256:<YOUR_GENERATED_CA_CERT_HASH> --cri-socket=unix:///var/run/crio/crio.sock

exit 0

# If you lost above information, you can get the token and hash by running following command on your CONTROL PLANE node:
# To get <YOUR_CONTROL_PLANE_NODE_IP>:
export K8S_NET_IP=$(ip addr show dev $(ip route show | awk '/^default/ {print $5}') | awk '/inet / {print $2}' | cut -d/ -f1)
echo "K8S_NET_IP=${K8S_NET_IP}"

# To get <YOUR_GENERATED_TOKEN>:
sudo kubeadm token create

# To get <YOUR_GENERATED_CA_CERT_HASH>:
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
openssl rsa -pubin -outform der 2>/dev/null | \
sha256sum | awk '{print $1}'
