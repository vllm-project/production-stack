# helm.tf

# Adds the NVIDIA Device Plugin to enable GPU access on vLLM pods
resource "helm_release" "nvidia_device_plugin" {
  name = "nvidia-device-plugin"

  repository = "https://nvidia.github.io/k8s-device-plugin"
  chart      = "nvidia-device-plugin"
  namespace  = "kube-addons"
  create_namespace = "true"

  set {
    name = "version"
    value = "0.17.0"
  }
}

# add vllm Helm Release
resource "helm_release" "vllm" {
  name       = "vllm"
  repository = "https://vllm-project.github.io/production-stack"
  chart      = "vllm-stack"

  values = [
    file(var.setup_yaml)
  ]

  depends_on = [
    helm_release.nvidia_device_plugin
  ]
}


# Add Prometheus Helm repository
resource "helm_release" "kube_prometheus_stack" {
  name             = "kube-prom-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  namespace        = "monitoring"
  create_namespace = true
  wait             = true

  values = [
    file(var.prom_stack_yaml)
  ]
}

# Install Prometheus Adapter
resource "helm_release" "prometheus_adapter" {
  name       = "prometheus-adapter"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "prometheus-adapter"
  namespace  = "monitoring"

  values = [
    file(var.prom_adapter_yaml)
  ]

  depends_on = [
    helm_release.kube_prometheus_stack
  ]
}
