################################################################################
# 1) vLLM Serving Engine (GPU) – Helm chart
################################################################################

resource "kubectl_manifest" "vllm_namespace" {
  count = var.enable_vllm && var.enable_nodepool_gpu ? 1 : 0

  yaml_body = <<YAML
apiVersion: v1
kind: Namespace
metadata:
  name: "${var.vllm_namespace}"
YAML

  depends_on = [null_resource.write_kubeconfig, terraform_data.wait_for_apiserver_dns]
}
#####################################################################################
# 2) HF Token
#####################################################################################

resource "kubectl_manifest" "hf_token" {
  count = var.enable_vllm && var.enable_nodepool_gpu ? 1 : 0

  yaml_body = <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: hf-token-secret
  namespace: "${var.vllm_namespace}" # Use the vllm_namespace variable
type: Opaque
stringData:
  token: "${var.hf_token}"
YAML

  depends_on = [kubectl_manifest.vllm_namespace]
}
######################
#  3) VLLM helm chart
######################

data "template_file" "vllm_values" {
    count = var.enable_vllm && var.enable_nodepool_gpu ? 1 : 0
  template = file( "${path.module}/${var.gpu_vllm_helm_config}" )  # Concatenate path.module and the variable
  vars = {
      org_id        = var.org_id
      cluster_name  = var.cluster_name # "vllm-gpu-cluster"
      issuer_name   = var.use_letsencrypt_staging ? "letsencrypt-staging" : "letsencrypt-prod"
      storage_class = "shared-vast"
      prefix       = var.vllm_host_prefix # "vllm-api"
      # NEW: Escape variables for the Jinja2 template
      lb = "{"
      rb = "}"
      pipe = "｜" # This is the specific DeepSeek full-width pipe. Full-width Pipe (｜, U+FF5C), tokenizer recognizes it as part of a Special Token ID
  }
}


# Helm release
resource "helm_release" "vllm_stack" {
  count = var.enable_vllm && var.enable_nodepool_gpu ? 1 : 0

  name             = "vllm-gpu-stack"
  repository       = "https://vllm-project.github.io/production-stack"
  chart            = "vllm-stack"
  namespace        = "${var.vllm_namespace}"
  create_namespace = false

  values = [data.template_file.vllm_values[0].rendered]
  timeout = 1260  # Wait up to 20 minutes for the release to be ready

  # Add cleanup settings
  cleanup_on_fail = true
  force_update    = true
  recreate_pods   = true
  wait            = true
  wait_for_jobs   = true

  depends_on = [
    kubectl_manifest.hf_token,           # optional
    helm_release.traefik,                 # Ensure Traefik is ready
    kubectl_manifest.letsencrypt_issuer-prod, # Ensure Let's Encrypt issuer is ready
    kubectl_manifest.letsencrypt_issuer-staging,
    kubectl_manifest.nodepool_gpu,
   terraform_data.wait_for_gpu_nodes     # Ensure GPU nodes are ready
  ]

}

#################################################################################
# 4) Observability stack VLLM
#################################################################################
resource "kubectl_manifest" "vllm_service_monitor" {
  for_each = var.enable_vllm && var.enable_nodepool_gpu ? toset(["vllm_monitor"]) : toset([])
  yaml_body = <<YAML
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: vllm-monitor
  namespace: kube-prometheus-stack
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchExpressions:
      - key: app.kubernetes.io/managed-by
        operator: In
        values: [Helm]
      - key: release
        operator: In
        values: [test, router]
      - key: environment
        operator: In
        values: [test, router]
  namespaceSelector:
    matchNames:
    - vllm
  endpoints:
  - port: router-sport
    path: /metrics
  - port: service-port
    path: /metrics
YAML

  depends_on = [helm_release.vllm_stack,
                 helm_release.kube_prometheus_stack]  # Ensure vLLM stack is ready before creating the ServiceMonitor
}

#    matchLabels:
#     app.kubernetes.io/instance: vllm-gpu-stack

######################################################
# 5) VLLM Dashboard integration with Prometheus
######################################################

locals {
  vllm_dashboard_cm = {
    apiVersion = "v1"
    kind       = "ConfigMap"
    metadata = {
      name      = "vllm-dashboard"
      namespace = "kube-prometheus-stack"
      labels = {
        grafana_dashboard = "1"
      }
    }
    data = {
      "vllm-dashboard.json" = file("${path.module}/config/vllm-dashboard.json")
    }
  }
}

resource "kubectl_manifest" "vllm_dashboard" {
  count     = var.enable_vllm && var.enable_nodepool_gpu ? 1 : 0
  yaml_body = yamlencode(local.vllm_dashboard_cm)

  depends_on = [helm_release.kube_prometheus_stack]
}


 #  Inference vLLM dashboard (per model)


locals {
  vllm_dashboard_oci_cm = {
    apiVersion = "v1"
    kind       = "ConfigMap"
    metadata = {
      name      = "vllm-model-dashboard"
      namespace = "kube-prometheus-stack"
      labels = {
        grafana_dashboard = "1"
      }
    }
    data = {
      "vllm-dashboard-oci.json" = file("${path.module}/config/vllm-dashboard-oci.json")
    }
  }
}

resource "kubectl_manifest" "vllm_dashboard_oci" {
  count     = var.enable_vllm && var.enable_nodepool_gpu ? 1 : 0
  yaml_body = yamlencode(local.vllm_dashboard_oci_cm)

  depends_on = [helm_release.kube_prometheus_stack]
}
