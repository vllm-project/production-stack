#!/bin/bash

# original kuberay installation reference: https://github.com/ray-project/kuberay?tab=readme-ov-file#helm-charts

# Add the Helm repo
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update

# Confirm the repo exists
helm search repo kuberay --devel

# Install both CRDs and KubeRay operator v1.1.0.
helm install kuberay-operator kuberay/kuberay-operator --version 1.1.0

# Check the KubeRay operator Pod in `default` namespace
kubectl get pods
# NAME                                READY   STATUS    RESTARTS   AGE
# kuberay-operator-78cb88fb88-gbw7w   0/1     Running   0          5s
