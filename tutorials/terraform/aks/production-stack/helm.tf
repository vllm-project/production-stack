# # helm.tf

# # Adds the NVIDIA Operator to enable GPU access on vLLM pods
resource "helm_release" "gpu_operator" {
  name       = "gpu-operator"
  namespace  = "gpu-operator"
  repository = "https://helm.ngc.nvidia.com/nvidia"
  chart      = "gpu-operator"
  version    = "v25.3.1"

  create_namespace = true
  wait             = true
}

# add vllm Helm Release
resource "helm_release" "vllm" {
  name       = "vllm"
  repository = "https://vllm-project.github.io/production-stack"
  chart      = "vllm-stack"
  timeout = 1200 #1200s

  values = [
    file(var.setup_yaml)
  ]

  depends_on = [
    helm_release.gpu_operator
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
