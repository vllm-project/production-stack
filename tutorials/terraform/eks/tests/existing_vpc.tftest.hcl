# Plan-only tests for the create_vpc = false (existing VPC) path. All providers
# are mocked, so no AWS credentials or cluster are needed:
#   terraform init -backend=false && terraform test

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a", "us-east-1b", "us-east-1c"] }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws", dns_suffix = "amazonaws.com" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012", arn = "arn:aws:iam::123456789012:user/test" }
  }
  mock_data "aws_region" {
    defaults = { name = "us-east-1", region = "us-east-1" }
  }
  mock_data "aws_iam_session_context" {
    defaults = { issuer_arn = "arn:aws:iam::123456789012:role/test", arn = "arn:aws:iam::123456789012:role/test" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/mock" }
  }
  mock_resource "aws_eks_cluster" {
    defaults = {
      arn                   = "arn:aws:eks:us-east-1:123456789012:cluster/vllm-eks"
      endpoint              = "https://mock.eks.amazonaws.com"
      certificate_authority = [{ data = "bW9jaw==" }]
      identity              = [{ oidc = [{ issuer = "https://oidc.eks.us-east-1.amazonaws.com/id/MOCK" }] }]
    }
  }
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/MOCK" }
  }
  mock_data "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000" }
  }
}
mock_provider "kubernetes" {}
mock_provider "helm" {}
mock_provider "kubectl" {}
mock_provider "tls" {}
mock_provider "local" {}
mock_provider "random" {}
mock_provider "time" {}
mock_provider "null" {}
mock_provider "template" {}
mock_provider "cloudinit" {}

variables {
  create_vpc = false
  vpc_id     = "vpc-0target"
  # vpc_cidr keeps its default (10.20.0.0/16): it belongs to the new-VPC path
  # and must not leak into the existing-VPC path.
  enable_efs_storage    = true
  enable_efs_csi_driver = true
  enable_vllm           = false
  hf_token              = "hf_dummy"
}

# The existing VPC has a secondary CIDR, as is common for EKS in shared VPCs.
override_data {
  target = data.aws_vpc.existing[0]
  values = {
    id         = "vpc-0target"
    cidr_block = "172.31.0.0/16"
    cidr_block_associations = [
      { association_id = "vpc-cidr-assoc-1", cidr_block = "172.31.0.0/16", state = "associated" },
      { association_id = "vpc-cidr-assoc-2", cidr_block = "100.64.0.0/16", state = "associated" },
    ]
  }
}

override_data {
  target = data.aws_vpc.selected
  values = { id = "vpc-0target", cidr_block = "172.31.0.0/16" }
}

# Two subnets share us-east-1a: EFS allows only one mount target per AZ.
override_data {
  target = data.aws_subnets.existing_private[0]
  values = { ids = ["subnet-0a1", "subnet-0a2", "subnet-0b1", "subnet-0c1"] }
}

override_data {
  target = data.aws_subnets.existing_public[0]
  values = { ids = [] }
}

override_data {
  target = data.aws_subnet.cluster_subnets[0]
  values = { id = "subnet-0a1", vpc_id = "vpc-0target", availability_zone = "us-east-1a", cidr_block = "172.31.0.0/20" }
}
override_data {
  target = data.aws_subnet.cluster_subnets[1]
  values = { id = "subnet-0a2", vpc_id = "vpc-0target", availability_zone = "us-east-1a", cidr_block = "172.31.16.0/20" }
}
override_data {
  target = data.aws_subnet.cluster_subnets[2]
  values = { id = "subnet-0b1", vpc_id = "vpc-0target", availability_zone = "us-east-1b", cidr_block = "172.31.32.0/20" }
}
override_data {
  target = data.aws_subnet.cluster_subnets[3]
  values = { id = "subnet-0c1", vpc_id = "vpc-0target", availability_zone = "us-east-1c", cidr_block = "100.64.0.0/20" }
}

run "private_subnet_lookup_is_scoped_to_vpc" {
  command = plan

  assert {
    condition = anytrue([
      for f in data.aws_subnets.existing_private[0].filter :
      f.name == "vpc-id" && contains(f.values, "vpc-0target")
    ])
    error_message = "existing_private subnet lookup must filter on vpc-id = var.vpc_id."
  }
}

run "efs_sg_allows_existing_vpc_cidrs" {
  command = plan

  assert {
    condition = alltrue([
      for r in aws_security_group.efs-sg[0].ingress :
      !contains(r.cidr_blocks, "10.20.0.0/16")
    ])
    error_message = "EFS SG must not use var.vpc_cidr when reusing an existing VPC."
  }

  assert {
    condition = alltrue([
      for c in ["172.31.0.0/16", "100.64.0.0/16"] :
      anytrue([for r in aws_security_group.efs-sg[0].ingress : contains(r.cidr_blocks, c)])
    ])
    error_message = "EFS SG must allow NFS from every CIDR associated with the existing VPC."
  }
}

run "one_efs_mount_target_per_az" {
  command = plan

  assert {
    condition     = length(aws_efs_mount_target.eks-efs-mounts) == 3
    error_message = "Expected one EFS mount target per AZ (3), not one per subnet."
  }

  assert {
    condition = length(distinct([
      for m in aws_efs_mount_target.eks-efs-mounts : m.subnet_id
    ])) == length(aws_efs_mount_target.eks-efs-mounts)
    error_message = "EFS mount targets must use distinct subnets."
  }
}

run "control_plane_subnets_span_two_azs" {
  command = plan

  # subnet-0a1 and subnet-0a2 are both in us-east-1a; EKS rejects that.
  assert {
    condition     = slice(local.private_subnet_ids_per_az, 0, 2) == tolist(["subnet-0a1", "subnet-0b1"])
    error_message = "Control plane subnets must come from two different AZs."
  }
}

# Regression check: the default new-VPC path keeps using var.vpc_cidr and one
# mount target per created private subnet.
run "new_vpc_path_unchanged" {
  command = plan

  variables {
    create_vpc = true
  }

  assert {
    condition     = toset(flatten([for r in aws_security_group.efs-sg[0].ingress : r.cidr_blocks])) == toset(["10.20.0.0/16"])
    error_message = "New-VPC path must keep allowing NFS from var.vpc_cidr."
  }

  assert {
    condition     = length(aws_efs_mount_target.eks-efs-mounts) == length(var.private_subnet_cidrs)
    error_message = "New-VPC path must keep one mount target per private subnet."
  }
}
