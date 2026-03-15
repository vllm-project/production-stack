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
