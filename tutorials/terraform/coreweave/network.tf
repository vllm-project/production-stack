
###############################################################################
# IP Pool (separate resource - Coreweave requirement)
###############################################################################
resource "coreweave_networking_vpc" "k8s" {
  name        = var.vpc_name # "vllm-vpc"
  zone        = var.zone
  # host_prefix = var.vpc_host_cidr
  vpc_prefixes = [
    {
      name  = "pod-cidr"
      value =   var.pod_cidr # "10.244.0.0/16"
    },
    {
      name  = "service-cidr"
      value =  var.service_cidr # "10.96.0.0/16"
    },
    {
      name  = "lb-cidr"
      value = var.lb_cidr # "10.20.0.0/22"
    },
  ]

  egress = {
    disable_public_access = false
  }

  ingress = {
    disable_public_services = false
  }

  dhcp = {
    dns = {
      servers = ["1.1.1.1", "8.8.8.8"]
    }
  }
}


####################################################
# INGRESS CONTROLLER
####################################################

#############################
# 2) Traefik (CoreWeave)
#############################

resource "helm_release" "traefik" {
 name             = "traefik"
 repository       = "https://charts.core-services.ingress.coreweave.com"
 chart            = "traefik"
 namespace        = "traefik"
 create_namespace = true

# This is the "Public DNS Name" logic from the docs applied to the Ingress Service
  set = [
    { name  = "service.annotations.service\\.beta\\.kubernetes\\.io/external-hostname" , value = "*"
    }

  ]

 depends_on = [coreweave_cks_cluster.k8s, terraform_data.wait_for_cpu_nodes]
}
