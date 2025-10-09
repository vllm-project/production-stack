################################################################################
# 3) vLLM Serving Engine (CPU) – Helm chart
################################################################################
# # --- Calico Cleanup (runs AFTER vLLM resources are destroyed) --------------
# resource "null_resource" "calico_cleanup" {
#   provisioner "local-exec" {
#     when    = destroy
#     command = <<EOF
#       kubectl delete apiservice v3.projectcalico.org --ignore-not-found
#       kubectl delete job -n tigera-operator tigera-operator-uninstall --ignore-not-found
#       kubectl -n tigera-operator delete job tigera-operator-delete-crds --ignore-not-found
# EOF
#   }

#   # This ensures cleanup runs AFTER vLLM resources are destroyed
#   # but BEFORE Calico helm release is destroyed
#   depends_on = [
#     helm_release.vllm_stack_cpu,  # Add your vLLM helm release here
#     kubernetes_secret.hf_token    # Add other vLLM resources here
#   ]
# }
# --- Namespace --------------------------------------------------------------
resource "kubernetes_namespace" "vllm" {
     for_each = var.enable_vllm ? toset(["vllm"]) : toset([])
  metadata {
    name = each.key # The name of the namespace will be "vllm"
  }
    timeouts {
    delete = "5m"  # Increase from default 5m
  }
    provisioner "local-exec" {
    when    = destroy
    command = <<-EOF
      KUBECONFIG=${path.module}/kubeconfig kubectl delete job -n tigera-operator tigera-operator-uninstall --ignore-not-found=true 2>/dev/null || true
      KUBECONFIG=${path.module}/kubeconfig kubectl delete job -n tigera-operator tigera-operator-delete-crds --ignore-not-found=true 2>/dev/null || true
      KUBECONFIG=${path.module}/kubeconfig kubectl delete apiservice v3.projectcalico.org --ignore-not-found=true 2>/dev/null || true
      KUBECONFIG=${path.module}/kubeconfig kubectl patch installation default --type=merge -p '{"metadata":{"finalizers":null}}' 2>/dev/null || true
      # Delete resources normally first
      # KUBECONFIG=${path.module}/kubeconfig kubectl delete ingress --all -n vllm --ignore-not-found=true || true
      # KUBECONFIG=${path.module}/kubeconfig kubectl delete targetgroupbinding.elbv2.k8s.aws --all -n vllm --ignore-not-found=true || true

      # KUBECONFIG=${path.module}/kubeconfig kubectl patch targetgroupbinding.elbv2.k8s.aws --all -n vllm --type=merge -p '{"metadata":{"finalizers":[]}}' || true
      # KUBECONFIG=${path.module}/kubeconfig kubectl patch ingress --all -n vllm --type=merge -p '{"metadata":{"finalizers":[]}}' || true
    EOF
   }
  depends_on = [module.eks, local_file.kubeconfig]  # Ensure Calico is ready before deploying vLLM
}

# manual removal of finalizers
# RESOURCE_NAME=$(kubectl get targetgroupbinding.elbv2.k8s.aws -n vllm -o jsonpath='{.items[0].metadata.name}')
# kubectl patch targetgroupbinding.elbv2.k8s.aws $RESOURCE_NAME -n vllm --type=merge -p '{"metadata":{"finalizers":[]}}'
# kubectl delete targetgroupbinding.elbv2.k8s.aws $RESOURCE_NAME -n vllm --ignore-not-found=true
# INGRESS_NAME=$(kubectl get ingress -n vllm -o jsonpath='{.items[0].metadata.name}')
# kubectl patch ingress $INGRESS_NAME -n vllm --type=merge -p '{"metadata":{"finalizers":[]}}'
# kubectl delete ingress $INGRESS_NAME -n vllm --ignore-not-found=true
# kubectl get namespace vllm -o jsonpath='{.spec.finalizers}'
# kubectl patch namespace vllm --type=merge -p '{"spec":{"finalizers":null}}'
# calico cleanup
# kubectl patch installation default --type=merge -p '{"metadata":{"finalizers":null}}'
# kubectl delete installation default --ignore-not-found=true


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
  template = file(
  var.inference_hardware == "gpu"
  ? "${path.module}/${var.gpu_vllm_helm_config}"
  : "${path.module}/${var.cpu_vllm_helm_config}"  # Concatenate path.module and the variable
)
  vars = {
    # Add any variables your template needs
  }
}


# Helm release
resource "helm_release" "vllm_stack" {
  count = var.enable_vllm ? 1 : 0

  name             = "vllm-${var.inference_hardware}"
  repository       = "https://vllm-project.github.io/production-stack"
  chart            = "vllm-stack"
  namespace        = kubernetes_namespace.vllm["vllm"].metadata[0].name
  create_namespace = false

  values = [data.template_file.vllm_values[0].rendered]
  timeout = 900  # Wait up to 15 minutes for the release to be ready

  # Add cleanup settings
  cleanup_on_fail = true
  force_update    = true
  recreate_pods     = true
  wait              = true
  wait_for_jobs     = true

 provisioner "local-exec" {
    when    = destroy
    command = <<-EOF
      KUBECONFIG=${path.module}/kubeconfig kubectl delete job -n tigera-operator tigera-operator-uninstall --ignore-not-found=true || true
      KUBECONFIG=${path.module}/kubeconfig kubectl delete job -n tigera-operator tigera-operator-delete-crds --ignore-not-found=true || true
      KUBECONFIG=${path.module}/kubeconfig kubectl delete apiservice v3.projectcalico.org --ignore-not-found=true || true
      KUBECONFIG=${path.module}/kubeconfig kubectl patch installation default --type=merge -p '{"metadata":{"finalizers":null}}'
    EOF
  }

  depends_on = [
    kubernetes_secret.hf_token,
    helm_release.calico,
    module.data_addons
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

  depends_on = [helm_release.vllm_stack]  # Ensure vLLM stack is ready before creating the ServiceMonitor
}

# vLLm Dashboard integration with Prometheus
resource "kubernetes_config_map" "vllm_dashboard" {
  count = var.enable_vllm ? 1 : 0
  metadata {
    name      = "vllm-dashboard"
    namespace = "kube-prometheus-stack"
    labels = {
      grafana_dashboard = "1"
    }
  }

  data = {
    "vllm-dashboard.json" = file("${path.module}/config/vllm-dashboard.json")
  }
    depends_on = [helm_release.vllm_stack]  # Ensure vLLM stack is ready before creating the ConfigMap
}

# 💡Destroy tips
# If you face terraform destroy issue due to vllm namespace stuck in "Terminating" state
# it's because Calico API discovery failure │ Error: NamespaceDeletionDiscoveryFailure.
# fix: delete the API service
# 2.  kubectl get APIServices v3.projectcalico.org
# 3.  kubectl delete apiservice v3.projectcalico.org
# Destroy Order: vLLM resources -> calico_cleanup (APIs/jobs) -> kubernetes_namespace.vllm
# example logs:
# vllm INFO 07-26 03:01:19 [metrics.py:486] Avg prompt throughput: 7.2 tokens/s, Avg generation throughput: 91.8 tokens/s, Running:
