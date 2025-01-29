helm upgrade kube-prom-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f "values.yaml"
