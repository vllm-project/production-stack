#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts

helm upgrade --install kube-prom-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  -f kube-prom-stack.yaml --wait

helm install prometheus-adapter prometheus-community/prometheus-adapter \
    --namespace monitoring \
    -f "$SCRIPT_DIR/prom-adapter.yaml"
