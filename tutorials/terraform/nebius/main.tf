################################################################################
#  Author: Kosseila HD (@CloudThrill)  --  re-tooled for Nebius
#  License: MIT
#  Date: Autumn 2025
#  Description: IaC for vLLM on Nebius Managed K8s – GPU-only, autoscaling,
#               shared filesystem, optional observability.
#  Part of the CloudThrill Kubernetes contribution to lm-cache vLLM-production-stack.
#  https://cloudthrill.ca
################################################################################

###############################################################################
# 0.  Nebius project & token helpers
###############################################################################
# If project_id is empty we use the CLI profile’s active project
data "nebius_iam_v1_project" "current" {
  count = var.neb_project_id == "" ? 1 : 0
}

locals {
  project_id = var.neb_project_id == "" ? data.nebius_iam_v1_project.current[0].id : var.neb_project_id
}

######################
# 0.1 platform locals
######################
locals {
  gpu_matrix = {
    "eu-north1" = {
      "gpu-h100-sxm" = "1gpu-16vcpu-200gb"
      "gpu-h200-sxm" = "1gpu-16vcpu-200gb"
      "gpu-b200-sxm" = "8gpu-160vcpu-1792gb"
    }
    "us-west1" = {
      "gpu-h100-sxm" = "1gpu-16vcpu-200gb"
      "gpu-h200-sxm" = "1gpu-16vcpu-200gb"
      "gpu-b200-sxm" = "8gpu-160vcpu-1792gb"
    }
  }
  platform_default_preset = {
    gpu-h100-sxm = "1gpu-16vcpu-200gb"
    gpu-h200-sxm = "1gpu-16vcpu-200gb"
    gpu-b200-sxm = "8gpu-160vcpu-1792gb"
    gpu-l40s-a   = "1gpu-8vcpu-32gb"     # Intel Ice-Lake  – smallest
    gpu-l40s-d   = "1gpu-16vcpu-96gb"    # AMD Genoa       – smallest
  }
gpu_preset = try(local.gpu_matrix[var.region][var.gpu_platform], local.platform_default_preset[var.gpu_platform])
# gpu_preset = can(local.gpu_matrix[var.region][var.gpu_platform]) ? local.gpu_matrix[var.region][var.gpu_platform] : local.platform_default_preset[var.gpu_platform]

  }


###############################################################################
# 1.  Budget & credit guard-rails (optional but recommended)
###############################################################################
# Creates a budget alert at 80 % of your remaining promotional credits.
# resource "nebius_billing_v1_budget" "gpu_budget" {
#   name        = "${var.cluster_name}-budget"
#   parent_id   = local.project_id
#   description = "Alert when 80 % of credits are consumed"

#   amount {
#     specified_amount {
#       currency_code = "USD"
#       units         = 100   # <-- adjust to your promo credit amount
#     }
#   }

#   threshold_rules {
#     percent = 80
#     spend_basis = "CURRENT_SPEND"
#     notification_email = car.ops_email # "info@example.com"  # <-- your ops email
#   }
# }

###############################################################################
# 3.  Managed Kubernetes cluster
###############################################################################
# resource "nebius_mk8s_v1_cluster" "k8s" {
#   name      = var.cluster_name
#   parent_id = local.project_id
#   labels    = var.tags

#   control_plane {
#     version   = var.k8s_version
#     subnet_id = nebius_vpc_v1_subnet.k8s.id
#     endpoints {
#       public_endpoint = var.public_endpoint ? {} : null
#     }
#   }
# }

resource "nebius_mk8s_v1_cluster" "k8s" {
  name      = var.cluster_name
  parent_id = var.neb_project_id
  labels    = var.tags

  control_plane = {
    endpoints = {
      public_endpoint = {}
    }
    version           = var.k8s_version
    subnet_id         = nebius_vpc_v1_subnet.k8s.id
    etcd_cluster_size = 1
  }
    kube_network = {
    service_cidrs = [var.service_cidr]  # Add this - e.g., "10.96.0.0/16"
  }
}
###############################################################################
# CPU Node Group (for system workloads)
###############################################################################
resource "nebius_mk8s_v1_node_group" "cpu" {
  name      = "${var.cluster_name}-cpu"
  parent_id = nebius_mk8s_v1_cluster.k8s.id

  template = {
    resources = {
      platform = "cpu-d3"
      preset   = "8vcpu-32gb"
    }
    boot_disk = {
      type           = var.cpu_disk_type  # Options: NETWORK_HDD , NETWORK_SSD_IO_M3,NETWORK_SSD_NON_REPLICATED
      size_gibibytes = var.cpu_disk_size_gb
    }
    network_interfaces = [{  # Array with single object
      subnet_id = nebius_vpc_v1_subnet.k8s.id
    }]

    #   cloud_init_user_data = templatefile("${path.module}/../modules/cloud-init/k8s-cloud-init.tftpl", {
    #   enable_filestore = var.enable_filestore ? "true" : "false",
    #   ssh_user_name    = var.ssh_user_name,
    #   ssh_public_key   = local.ssh_public_key
    # })
  }

  autoscaling = {
    max_node_count = var.cpu_node_max
    min_node_count = var.cpu_node_min
  }
}

###############################################################################
# GPU Node Group (H100 - modify as needed)
###############################################################################
resource "nebius_mk8s_v1_node_group" "gpu" {
  name      = "${var.cluster_name}-gpu"
  parent_id = nebius_mk8s_v1_cluster.k8s.id

  template = {
    resources = {
      platform = var.gpu_platform # "gpu-h100-sxm"      # Options: gpu-h100-sxm, gpu-h200-sxm, gpu-b200-sxm
      preset   = local.gpu_preset  # "8gpu-128vcpu-1600gb"
    }
    boot_disk = {
      type           = var.gpu_disk_type # Options: NETWORK_HDD , NETWORK_SSD_IO_M3,NETWORK_SSD_NON_REPLICATED
      size_gibibytes = var.gpu_disk_size_gb
    }
    network_interfaces = [{  # Array with single object
      subnet_id = nebius_vpc_v1_subnet.k8s.id
    }]
    # Optional: GPU cluster for InfiniBand
    # gpu_cluster ={
    #   id = nebius_compute_v1_gpu_cluster.main.id
    # }
    # GPU-specific settings
    # os = "ubuntu22.04"  # Explicitly specify Ubuntu 22.04
    gpu_settings = {
      drivers_preset = "cuda12"  # or "cuda12.4", "cuda12.8" depending on platform/k8s version
    }

    metadata = {
      labels = merge(var.tags, { workload = "gpu" })
    }

    taints = [{  # Array with single object
      key    = "nvidia.com/gpu"
      value  = "true"
      effect = "NO_SCHEDULE"
    }]

    #  cloud_init_user_data = templatefile("${path.module}/../modules/cloud-init/k8s-cloud-init.tftpl", {
    #   enable_filestore = var.enable_filestore ? "true" : "false",
    #   ssh_user_name    = var.ssh_user_name,
    #   ssh_public_key   = local.ssh_public_key
    # })
  }

  autoscaling = {
    max_node_count = 2
    min_node_count = 1
  }
}


# ###############################################################################
# # 5.  Shared ReadWriteMany filesystem
# ###############################################################################
# resource "nebius_filesystem_v1_filesystem" "shared" {
#   name       = "${var.cluster_name}-shared"
#   parent_id  = local.project_id
#   zone       = var.zone
#   size       = var.shared_fs_size_tb * 1024 * 1024 * 1024 * 1024   # TiB → bytes
#   type       = var.shared_fs_type
#   network_id = local.vpc_id
#   labels     = var.tags
# }

###############################################################################
# 6.  Kubeconfig file for local usage
###############################################################################
# data "nebius_client_config" "default" {}
resource "local_file" "kubeconfig" {
  content = templatefile("${path.module}/config/kubeconfig.tpl", {
    cluster_name     = nebius_mk8s_v1_cluster.k8s.name
    cluster_endpoint = nebius_mk8s_v1_cluster.k8s.status.control_plane.endpoints.public_endpoint
    cluster_ca       = base64encode(nebius_mk8s_v1_cluster.k8s.status.control_plane.auth.cluster_ca_certificate)
    profile          = var.neb_profile
  })
  filename             = "${path.module}/kubeconfig"
  file_permission      = "0600"
  directory_permission = "0755"
}

###############################################################################
# export NB_PROFILE=cloudthrill
# terraform init
# terraform apply -auto-approve
# export KUBECONFIG=$PWD/kubeconfig
# kubectl get nodes
