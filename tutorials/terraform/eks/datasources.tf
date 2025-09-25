# Data source to get the current user ID
data "aws_caller_identity" "current" {}
# Data source to get the EKS managed KMS key This is used for encrypting secrets in the EKS cluster
data "aws_kms_key" "eks_managed_key" {
  key_id = "alias/aws/eks"
}

# Data source to get available AZs for the current region
data "aws_availability_zones" "available" { # automatically uses the region configured in the AWS provider.
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

# Local values to process the AZs
locals {
  # Take first 3 AZs from the region
  azs = slice(data.aws_availability_zones.available.names, 0, 3)
}

# Data source for the VPC
data "aws_vpc" "selected" {
  id = local.vpc_id
}

# Data sources for cluster subnets (private)
data "aws_subnet" "cluster_subnets" {
  count = length(local.private_subnet_ids)
  id    = local.private_subnet_ids[count.index]
}

# Data sources for cluster subnets (public)
data "aws_subnet" "cluster_public_subnets" {
  count = length(local.public_subnet_ids)
  id    = local.public_subnet_ids[count.index]
}

##########################
# VLLM Ingress
##########################

# Data source that only tries to read ingress if vLLM is enabled
data "kubernetes_ingress_v1" "vllm_ingress" {
  count = var.enable_vllm ? 1 : 0

  metadata {
    name      = "vllm-gpu-ingress-router"  # Adjust to match your actual ingress name
    namespace = kubernetes_namespace.vllm["vllm"].metadata[0].name
  }

  depends_on = [helm_release.vllm_stack]
}
