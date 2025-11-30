################################################################################
# 3) vLLM Serving Engine (CPU) – Helm chart
################################################################################

# --- Namespace --------------------------------------------------------------
resource "kubernetes_namespace" "vllm" {
     for_each = var.enable_vllm ? toset(["vllm"]) : toset([])
  metadata {
    name = each.key # The name of the namespace will be "vllm"
  }
    timeouts {
    delete = "5m"  # Increase from default 5m
  }

  depends_on = [nebius_mk8s_v1_cluster.k8s,
               local_file.kubeconfig,
                nebius_mk8s_v1_node_group.cpu,
                nebius_mk8s_v1_node_group.gpu,  ]
}



# --- Hugging-Face token (opaque secret) -------------------------------------
resource "kubernetes_secret" "hf_token" {
  for_each = var.enable_vllm ? toset(["hf_token"]) : toset([])
  metadata {
    name      = "hf-token-secret"
    # This should be kubernetes_namespace.vllm["vllm"], not vllm_namespace
    namespace = kubernetes_namespace.vllm["vllm"].metadata[0].name
  }

  type = "Opaque"
  data = {
    token =  var.hf_token
    }
}

######################
#  VLLM helm chart
######################

data "template_file" "vllm_values" {
    count = var.enable_vllm ? 1 : 0
  template = file( "${path.module}/${var.gpu_vllm_helm_config}" )  # Concatenate path.module and the variable
  vars = {
    nginx_ip_hex = local.nginx_ip_hex  # Add this line
  }
}


# Helm release
resource "helm_release" "vllm_stack" {
  count = var.enable_vllm ? 1 : 0

  name             = "vllm-gpu-stack"
  repository       = "https://vllm-project.github.io/production-stack"
  chart            = "vllm-stack"
  namespace        = kubernetes_namespace.vllm["vllm"].metadata[0].name
  create_namespace = false

  values = [data.template_file.vllm_values[0].rendered]
  timeout = 900  # Wait up to 15 minutes for the release to be ready

  # Add cleanup settings
  cleanup_on_fail = true
  force_update    = true
  recreate_pods   = true
  wait            = true
  wait_for_jobs   = true

  depends_on = [
    kubernetes_secret.hf_token,
  #  nebius_applications_v1alpha1_k8s_release.ingress,
    helm_release.nginx_ingress,  # Ensure NGINX Ingress is ready before deploying vLLM
    kubectl_manifest.letsencrypt_issuer,  # Ensure Let's Encrypt issuer is ready
    nebius_mk8s_v1_node_group.gpu  # Ensure GPU node group is ready
  ]

}

#################################################################################
# Observability stack VLLM
#################################################################################
resource "kubectl_manifest" "vllm_service_monitor" {
  count = var.enable_vllm ? 1 : 0
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

# vLLm Dashboard integration with Prometheus
resource "kubernetes_config_map" "vllm_dashboard" {
  count = var.enable_vllm ? 1 : 0
  metadata {
    name      = "vllm-dashboard"
    namespace = "kube-prometheus-stack"  # kube-prometheus-stack
    labels = {
      grafana_dashboard = "1"
    }
  }

  data = {
    "vllm-dashboard.json" = file("${path.module}/config/vllm-dashboard.json")
  }
    depends_on = [helm_release.vllm_stack, helm_release.kube_prometheus_stack]  # Ensure vLLM stack is ready before creating the ConfigMap
}

# 💡Destroy tips
