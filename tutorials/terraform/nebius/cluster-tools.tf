# cluster-tools.tf
###################################################################
# Cert manager for Kubernetes
###################################################################

# cert-manager (Nebius catalog)
resource "nebius_applications_v1alpha1_k8s_release" "cert_manager" {
  cluster_id       = nebius_mk8s_v1_cluster.k8s.id
  parent_id        = var.neb_project_id
  application_name = "cert-manager"
  namespace        = "cert-manager"
  product_slug     = "bitnami/cert-manager"

  set = {
    "installCRDs" : "true",
    "ingressShim.defaultIssuerName" : "letsencrypt-prod",
    "ingressShim.defaultIssuerKind" : "ClusterIssuer"
  }
}


# ClusterIssuer for Let's Encrypt
resource "kubectl_manifest" "letsencrypt_issuer" {
  count = var.enable_cert_manager ? 1 : 0

  yaml_body = templatefile(
    "${path.module}/config/manifests/letsencrypt-issuer.yaml",
    {
      letsencrypt_email = var.letsencrypt_email
    }
  )

  depends_on = [
   # helm_release.cert_manager
     nebius_applications_v1alpha1_k8s_release.cert_manager
  ]
}

##########################
# Observability Stack
##########################

resource "helm_release" "kube_prometheus_stack" {
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
        nginx_ip_hex          = local.nginx_ip_hex
        grafana_admin_password = var.grafana_admin_password
        # dns_prefix             = var.prefix
        # location               = var.location
      }
    )
  ]

  depends_on = [
   nebius_applications_v1alpha1_k8s_release.cert_manager,
   # helm_release.cert_manager,          # cert-manager must be up first
    kubectl_manifest.letsencrypt_issuer, # ClusterIssuer must exist
    nebius_mk8s_v1_cluster.k8s,
    nebius_mk8s_v1_node_group.cpu,
    nebius_mk8s_v1_node_group.gpu,
    data.kubernetes_service.nginx_ingress
  ]
}


#####################################################
# Observability Stack - using application Module (Nebius catalog)
# #####################################################

# resource "nebius_applications_v1alpha1_k8s_release" "prometheus" {
#   cluster_id = nebius_mk8s_v1_cluster.k8s.id
#   parent_id  = var.neb_project_id

#   application_name = "grafana-and-prometheus"
#   namespace        = "kube-prometheus-stack"
#   product_slug     = "nebius/grafana-and-prometheus"

#   set = {
#     "prometheus.alertmanager.enabled" : true,  # Enable Alertmanager
#     "prometheus.prometheus-pushgateway.enabled" : false,
#     "prometheus.prometheus-node-exporter.enabled" : true,
#     "grafana.adminPassword" : var.grafana_admin_password,
#     "prometheus.server.scrape_interval" : var.prometheus_scrape_interval,
#     "prometheus.server.retention" : var.prometheus_retention,
#     "prometheus.server.persistentVolume.size" : var.prometheus_pv_size

#   }

#   depends_on = [
#     nebius_mk8s_v1_node_group.cpu ,
#     nebius_mk8s_v1_node_group.gpu ,
#   ]
# }
# ###################################################
# Cert manager using Helm chart
#####################################################
# resource "helm_release" "cert_manager" {
#   name       = "cert-manager"
#   repository = "https://charts.jetstack.io"
#   chart      = "cert-manager"
#   namespace  = "cert-manager"
#   version    = "v1.15.5"

#   create_namespace = true
#   set = [
#     { name = "installCRDs", value = "true" },
#     # For Azure GKE with HTTP Application Routing
#     { name = "ingressShim.defaultIssuerName", value = "letsencrypt-prod" },
#     { name = "ingressShim.defaultIssuerKind", value = "ClusterIssuer" }
#   ]

#   depends_on = [
#     nebius_mk8s_v1_cluster.k8s
#   ]
# }
