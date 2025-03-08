#!/bin/bash

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install kube-prom-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml
