#  nebius iam tenant list --format json | jq -r '.items[].metadata.name'
# Get current tenant information
# data "nebius_iam_v2_tenant" "current" {
#  count = var.enable_loki ? 1 : 0
#   # You can look up by name if you know it
#   name = var.tenant_name

#   # Or by ID if you already have it
#   # id = "tenant-xxx"
# }
#######################################################
#       Ingress EndPoints
#######################################################

data "kubernetes_ingress_v1" "grafana" {
  metadata {
    name      = "${helm_release.kube_prometheus_stack.name}-grafana"
    namespace = helm_release.kube_prometheus_stack.namespace
  }

  depends_on = [helm_release.kube_prometheus_stack]
}
##########################
# VLLM Ingress
##########################
# Data source to dynamically find the vLLM ingress created by the Helm chart
data "kubernetes_resources" "vllm_ingresses" {
  count = var.enable_vllm ? 1 : 0

  api_version = "networking.k8s.io/v1"
  kind        = "Ingress"
  namespace   = kubernetes_namespace.vllm["vllm"].metadata[0].name

  depends_on = [helm_release.vllm_stack]
}

# Helper locals to extract ingress data
locals {
  vllm_ingress_data = var.enable_vllm ? [
    for ingress in data.kubernetes_resources.vllm_ingresses[0].objects : ingress
    if can(ingress.metadata.annotations["cert-manager.io/cluster-issuer"])
  ] : []

  vllm_ingress_host = length(local.vllm_ingress_data) > 0 ? try(
    local.vllm_ingress_data[0].spec.rules[0].host,
    "pending"
  ) : "not-deployed"
}
