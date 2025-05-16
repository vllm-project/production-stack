#!/bin/bash

# Refer to https://docs.tigera.io/calico/latest/getting-started/kubernetes/quickstart
# for more information.

# Install the Tigera operator and custom resource definitions:
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.30.0/manifests/tigera-operator.yaml

# Install Calico by creating the necessary custom resources:
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.30.0/manifests/custom-resources.yaml
