
###############################################################################
# IP Pool (separate resource - Nebius requirement)
###############################################################################
resource "nebius_vpc_v1_pool" "main" {
  name      = "${var.cluster_name}-pool"
  parent_id = var.neb_project_id

  version    = "IPV4"
  visibility = "PRIVATE"

  cidrs = [{
    cidr            = var.vpc_cidr  # 10.20.0.0/16
    max_mask_length = 24
  },
    {
      cidr            = var.service_cidr   # 10.96.0.0/16 - ADD THIS
      max_mask_length = 16
    }
  ]
}
###############################################################################
# Network
###############################################################################
resource "nebius_vpc_v1_network" "k8s" {
  name      = "${var.cluster_name}-network"
  parent_id = var.neb_project_id
  ipv4_private_pools = {
    pools = [
      {     id = nebius_vpc_v1_pool.main.id }
    #   {
    #   cidrs = [{
    #     cidr            = var.vpc_cidr  # Use variable
    #     max_mask_length = 24
    #   }]
    # }
    ]
  }
  labels    = var.tags
}

resource "nebius_vpc_v1_subnet" "k8s" {
  name            = "${var.cluster_name}-subnet"
  parent_id       =  var.neb_project_id
  network_id      = nebius_vpc_v1_network.k8s.id   # VPC
   ipv4_private_pools = {
    use_network_pools = false
    pools = [ {
               cidrs = [{ cidr = var.vpc_cidr },
                        #  { cidr = var.subnetwork2_cidr },
                        #  { cidr = var.subnetwork3_cidr },
                         { cidr = var.service_cidr }   # Add service CIDR here too
                       ]
             } ]
  }
  labels    = var.tags
}

####################################################
# INGRESS CONTROLLER
####################################################
# Reserved IP for GKE native Ingress Controller
# Nginx Ingress Controller with Helm

# Deploy NGINX Ingress Controller
resource "helm_release" "nginx_ingress" {
  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  namespace  = "ingress-nginx"

  create_namespace = true

values = [
   <<-EOF
    controller:
      service:
        type: LoadBalancer
        externalTrafficPolicy: Cluster  # Changed from Local to Cluster
        annotations:
      # Nebius Load Balancer annotations (if needed)
      #   service.beta.kubernetes.io/nebius-load-balancer-type: "external"
      # service.beta.kubernetes.io/nebius-load-balancer-subnet-id: "your-subnet-id"
      # nebius.com/load-balancer-allocation-id: "your-allocation-id"

      config:
        proxy-body-size: "100m"
        client-max-body-size: "100m"
        proxy-read-timeout: "600"
        proxy-send-timeout: "600"
        proxy-connect-timeout: "60"

      metrics:
        enabled: true

      podAnnotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "10254"
    EOF
  ]

  depends_on = [nebius_mk8s_v1_cluster.k8s]
}

# Get the LoadBalancer IP
data "kubernetes_service" "nginx_ingress" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = "ingress-nginx"
  }

  depends_on = [
     helm_release.nginx_ingress
    # nebius_applications_v1alpha1_k8s_release.ingress
    ]
}

locals {
  nginx_ip =  data.kubernetes_service.nginx_ingress.status.0.load_balancer.0.ingress.0.ip
  nginx_ip_hex = join("", formatlist("%02x", split(".", local.nginx_ip)))  #
}

####################################################
# Nginx using nebius applications resource
####################################################
#
# resource "nebius_applications_v1alpha1_k8s_release" "ingress" {
#   cluster_id       = nebius_mk8s_v1_cluster.k8s.id
#   parent_id        = var.neb_project_id
#   application_name = "nginx-ingress-controller"
#   namespace        = "ingress-nginx"
#   product_slug     = "bitnami/nginx-ingress-controller"

#   set = {
#     # Service configuration
#     "controller.service.type"                = "LoadBalancer"
#     "controller.service.externalTrafficPolicy" = "Cluster"

#     # Config settings
#     "controller.config.proxy-body-size"        = "100m"
#     "controller.config.client-max-body-size"   = "100m"
#     "controller.config.proxy-read-timeout"     = "600"
#     "controller.config.proxy-send-timeout"     = "600"
#     "controller.config.proxy-connect-timeout"  = "60"

#     # Metrics
#     "controller.metrics.enabled"               = "true"

#     # Pod annotations
#     "controller.podAnnotations.prometheus.io/scrape" = "true"
#     "controller.podAnnotations.prometheus.io/port"   = "10254"
#     #
#   }

#   depends_on = [
#     nebius_mk8s_v1_node_group.cpu,
#     nebius_mk8s_v1_node_group.gpu,
#     nebius_mk8s_v1_cluster.k8s, # from original depends_on
#   ]
# }
# # Create VPC Network
# resource "nebius_vpc_v1_network" "test" {
#   name      = "test-vpc"
#   parent_id = var.neb_project_id

#   labels = {
#     purpose = "terraform-test"
#     created = "cloudthrill"
#   }
# }
#####################################################
