## -------------------------------------------------------------------------------------------
##  Author: Kosseila HD (@CloudThrill)
##  License: MIT
##  Date: Summer 2025
##  Description: Infrastructure as Code for vLLM in EKS with Calico CNI, Cert-Manager,
##               , and observability stack (Grafana, Prometheus).
##
##  Part of the CloudThrill Kubernetes contribution to lm-cache vLLMproduction-stack project.
##  https://cloudthrill.ca
## -------------------------------------------------------------------------------------------

################################################################################
# Dynamic node-group map (CPU mandatory, GPU optional)
################################################################################
locals {
  # --- 1️⃣  CPU pool (always present) ---
  base_cpu_pool = {
    cpu_pool = {
      min_size       = var.cpu_node_min_size
      max_size       = var.cpu_node_max_size
      desired_size   = var.cpu_node_desired_size
      ami_type       = "AL2023_x86_64_STANDARD" # EKS-optim
      instance_types = var.cpu_node_instance_types # t3.medium (2 vCPU, 4 GiB RAM),
      # t3.xlarge (4 vCPU, 16 GiB RAM) t3.2xlarge (8 vCPU, 32 GiB RAM), t3a.large AMD EPYC (2 vCPU, 8 GiB RAM)
      capacity_type  = "ON_DEMAND"
      subnet_ids     = local.private_subnet_ids
      # disk_size      = 50  # Add this for 50GB root volume
            # Remove disk_size and use block_device_mappings instead
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size = 50  # Your desired 50GB
            volume_type = "gp3"
            encrypted   = true
            delete_on_termination = true
          }
        }
      }
      labels = {
      "workload-type" = "cpu"
      "node-group" = "cpu-pool"
    }
     iam_role_additional_policies = {
        Amazon_EBS_CSI_Driver = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
      }
    }
  }

  # --- 2️⃣  GPU pool (only when inference_hardware = "gpu") ---
  gpu_pool = {
    gpu_pool = {
      min_size       = var.gpu_node_min_size
      max_size       = var.gpu_node_max_size
      desired_size   = var.gpu_node_desired_size
      instance_types = var.gpu_node_instance_types        # "g4dn.xlarge" NVIDIA T4 (16 GiB GPU mem)
      ami_type       = "AL2023_x86_64_NVIDIA" # EKS-optimised GPU AMI
      ebs_optimized        = true
      subnet_ids     = [element(local.private_subnet_ids, 0)]
      capacity_type  = var.gpu_capacity_type # "SPOT"
      # disk_size      = 60  # launch-template overwrite this root volume value 60GB replace with below
            # Use block_device_mappings for GPU nodes too
      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size = 100  # Your desired 60GB
            volume_type = "gp3"
            encrypted   = true
            delete_on_termination = true
            # snapshot_id = null   ensure no snapshot-based volume creation occurs
          }
        }
      }
      labels = {
      "workload-type" = "gpu"
      "node-group"    = "gpu-pool"
      }
      taints = [{
        key    = "nvidia.com/gpu"
        value  = "Exists"
        effect = "NO_SCHEDULE"
      }]
     iam_role_additional_policies = {
        Amazon_EBS_CSI_Driver = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
      }
    }
  }

  # --- 3️⃣  Final map passed to the EKS module ---
  # node_groups_map = lower(var.inference_hardware) == "gpu" ? merge(local.base_cpu_pool, local.gpu_pool) : local.base_cpu_pool
node_groups_map = merge(
  local.base_cpu_pool,
  lower(var.inference_hardware) == "gpu" ? local.gpu_pool : {}
)
}

module "eks" {
  source = "git::https://github.com/cloudthrill/terraform-aws-eks-modules.git//aws-eks?ref=v1.0.0"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version
  # Control plane public, nodes private
  cluster_endpoint_public_access = var.api_public_access
  # resources within your VPC (worker nodes, Lambda functions, EC2 instances) can communicate with the API server internally not via internet
  cluster_endpoint_private_access = var.api_private_access

  vpc_id = local.vpc_id
  # control_plane_subnet_ids = module.vpc.private_subnets  # will fall back to subnets_ids if attribute is skipped
  subnet_ids = slice(local.private_subnet_ids, 0, 2) # Use only first two private subnets for control plane. You can also use all private subnets for more IPs.
  enable_irsa = true

  ## Public access endpoint is provided through AWS's managed service layer (proxy), not through your VPC's public subnets
  cluster_endpoint_public_access_cidrs = var.api_public_access_cidrs
  # Give Terraform identity admin access to the cluster which will allow resources to be deployed into cluster
  enable_cluster_creator_admin_permissions = var.enable_cluster_creator_admin_permissions
  eks_managed_node_groups                  = local.node_groups_map
  ############################
  # Disable custom KMS key creation to avoid KMS costs while maintaining security
  # Keep cluster_encryption_config at its default to maintain encryption with AWS-managed keys
  create_kms_key = false
  cluster_encryption_config = {
  resources        = ["secrets"]
  provider_key_arn = data.aws_kms_key.eks_managed_key.arn
}
  # Disable cluster encryption entirely (uses AWS-managed keys)
  # cluster_encryption_config = {}
  # Disable CloudWatch logging entirely
  cluster_enabled_log_types = []
  create_cloudwatch_log_group = false
  # Create the CloudWatch log group
  # create_cloudwatch_log_group = false
  # Only enable essential log types instead of all
  # cluster_enabled_log_types = ["audit"]  # Instead of ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  tags = var.tags
}

########################################
# Kubernetes kubeconfig file
########################################
resource "local_file" "kubeconfig" {
  content = templatefile("${path.module}/config/kubeconfig.tpl", {
    cluster_name     = module.eks.cluster_name
    cluster_endpoint = module.eks.cluster_endpoint
    cluster_ca       = module.eks.cluster_certificate_authority_data
    region           = var.region
    profile          = local.aws_profile          #  ← NEW
  })
  filename             = "${path.module}/kubeconfig"
  file_permission      = "0600"
  directory_permission = "0755"
}
