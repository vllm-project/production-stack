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