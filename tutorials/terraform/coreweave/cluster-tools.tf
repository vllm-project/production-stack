###############################################################################
# cluster-tools.tf
# - Traefik (CoreWeave)
# - cert-manager (CoreWeave) + manual ClusterIssuers (prod+staging, Traefik-pinned)
# - metrics-server (upstream)
# - kube-prometheus-stack (upstream) with Grafana ingress + dashboard sidecar
###############################################################################

###############################
# 1) Metrics Server (Upstream)
###############################
resource "helm_release" "metrics_server" {
   for_each = var.enable_metrics_server ? toset(["metrics_server"]) : toset([])
  name       = "metrics-server"
  repository = "https://kubernetes-sigs.github.io/metrics-server/"
  chart      = "metrics-server"
  version    = "3.12.0"
  namespace  = "kube-system"

  values = [<<-EOT
replicas: 2
podDisruptionBudget:
  enabled: true
  maxUnavailable: 1
EOT
  ]
  wait    = false
  timeout = 900
  depends_on = [coreweave_cks_cluster.k8s, terraform_data.wait_for_cpu_nodes]
}

#############################
# 2) cert-manager (CoreWeave) - issuers disabled (we manage them manually)
############################

resource "helm_release" "cert_manager" {
  for_each = var.enable_cert_manager ? toset(["cert-manager"]) : toset([])
  name             = "cert-manager"
  repository       = "https://charts.core-services.ingress.coreweave.com"
  chart            = "cert-manager"
  namespace        = "cert-manager"
  create_namespace = true

  # We keep full control of ClusterIssuers to pin ACME HTTP-01 solver to Traefik.
  set = [
     { name  = "cert-issuers.enabled", value = "false" }
  ]
  wait    = true
  timeout = 600
  depends_on = [helm_release.traefik]
}

####################################
# 3) ClusterIssuer for Let's Encrypt
####################################

resource "kubectl_manifest" "letsencrypt_issuer-prod" {
  for_each = var.enable_cert_manager ? toset(["letsencrypt"]) : toset([])

  yaml_body = templatefile(
    "${path.module}/config/manifests/letsencrypt-issuer-prod.yaml",
    {
      letsencrypt_email = var.letsencrypt_email
    }
  )

  depends_on = [
    helm_release.cert_manager
  ]
}

resource "kubectl_manifest" "letsencrypt_issuer-staging" {
  for_each = var.enable_cert_manager ? toset(["letsencrypt"]) : toset([])

  yaml_body = templatefile(
    "${path.module}/config/manifests/letsencrypt-issuer-stage.yaml",
    {
      letsencrypt_email = var.letsencrypt_email
    }
  )

  depends_on = [
    helm_release.cert_manager
  ]
}

##########################
# 4) Observability Stack
##########################

resource "helm_release" "kube_prometheus_stack" {
  for_each = var.enable_monitoring ? toset(["kube_prometheus_stack"]) : toset([])
  name             = "kube-prometheus-stack"
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  namespace        = "kube-prometheus-stack" #
  version          = "75.15.0"
  create_namespace = true

  values = [
    templatefile(
      "${path.module}/config/helm/kube-prome-stack.yaml",
      {
       grafana_admin_password = var.grafana_admin_password
        grafana_host           = "grafana.${var.org_id}-${var.cluster_name}.coreweave.app"
        issuer_name            = var.use_letsencrypt_staging ? "letsencrypt-staging" : "letsencrypt-prod"
        org_id                 = var.org_id
        cluster_name           = var.cluster_name # "vllm-gpu-cluster"
         prefix                 = var.grafana_host_prefix
      }
    )
  ]

  depends_on = [
    helm_release.traefik,
    kubectl_manifest.letsencrypt_issuer-prod,
    kubectl_manifest.letsencrypt_issuer-staging,
    terraform_data.wait_for_cpu_nodes  # Ensure CPU nodes ready before deploying
  ]
}

#################################################################################
# 5) Wait for latest CPU nodepool is ready - terraform_data with local-exec provisioner
################################################################################

resource "terraform_data" "wait_for_cpu_nodes" {
  count = var.enable_nodepool_cpu ? 1 : 0

  input = sha1(kubectl_manifest.nodepool_cpu["cpu"].yaml_body)

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command = <<-EOT
      set -euo pipefail
      POOL="${var.cpu_nodepool_name}"
      TARGET="${var.cpu_node_target}"
      KUBECONFIG="${path.module}/kubeconfig"

      for _ in $(seq 1 240); do
        READY=$(kubectl --kubeconfig "$KUBECONFIG" get nodes \
          -l "compute.coreweave.com/node-pool=$POOL" \
          --no-headers 2>/dev/null \
          | awk '$2=="Ready"{c++} END{print c+0}')

        [ "$READY" -ge "$TARGET" ] && exit 0
        sleep 10
      done
      exit 1
    EOT
  }

  depends_on = [
    kubectl_manifest.nodepool_cpu,
    null_resource.write_kubeconfig
  ]
}

################################################################################
# 6) GPU Nodepool with kubelet config (taints, scale down strategy, eviction)
################################################################################
# you can use this for more tolerant Ready match:  awk '$2 ~ /Ready/ && $2 !~ /NotReady/ {c++} END{print c+0}'
resource "terraform_data" "wait_for_gpu_nodes" {
  count = var.enable_nodepool_gpu ? 1 : 0

  input = sha1(kubectl_manifest.nodepool_gpu["gpu"].yaml_body)

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command = <<-EOT
      set -euo pipefail
      POOL="${var.gpu_nodepool_name}"
      TARGET="${var.gpu_node_target}"
      KUBECONFIG="${path.module}/kubeconfig"

      for _ in $(seq 1 240); do
        READY=$(kubectl --kubeconfig "$KUBECONFIG" get nodes \
          -l "compute.coreweave.com/node-pool=$POOL" \
          --no-headers 2>/dev/null \
          | awk '$2=="Ready"{c++} END{print c+0}')

        [ "$READY" -ge "$TARGET" ] && exit 0
        sleep 10
      done
      exit 1
    EOT
  }

  depends_on = [
    kubectl_manifest.nodepool_gpu,
    null_resource.write_kubeconfig
  ]
}


#########################################
# Cluster API DNS endpoint ready
#########################################

resource "terraform_data" "wait_for_apiserver_dns" {
  depends_on = [null_resource.write_kubeconfig]

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-lc"]
    command = <<-EOT
      set -euo pipefail
      KUBECONFIG="${path.module}/kubeconfig"

      # Extract server hostname from kubeconfig
      HOST="$(kubectl --kubeconfig "$KUBECONFIG" config view --raw -o jsonpath='{.clusters[0].cluster.server}' \
        | sed -E 's#^https?://##' | cut -d/ -f1)"

      echo "Waiting for API DNS: $HOST"

      for _ in $(seq 1 120); do
        if getent hosts "$HOST" >/dev/null 2>&1; then
          echo "DNS OK: $HOST"
          exit 0
        fi
        sleep 5
      done

      echo "API DNS did not resolve in time: $HOST" >&2
      exit 1
    EOT
  }
}
