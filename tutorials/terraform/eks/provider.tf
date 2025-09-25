# Copyright (c) 2025, Kosseila HD (Cloudthrill), released under MIT License.
locals {
  aws_profile = var.aws_profile != "default" ? var.aws_profile : "default"
}

provider "aws" {
  region  = var.region
  profile = local.aws_profile
  # If you have multiple profiles, you can set the profile here or use the AWS_PROFILE environment variable
}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.32"
      # https://registry.terraform.io/providers/hashicorp/kubernetes/
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.15"
      # https://registry.terraform.io/providers/hashicorp/helm/
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = ">= 2.5"
      # https://registry.terraform.io/providers/hashicorp/local/
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.19.0"
    }
  }
  required_version = "~> 1.0"
}


# Kubernetes provider configuration
provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    # This requires the awscli to be installed locally where Terraform is executed
    args = concat(
      ["eks", "get-token",
        "--cluster-name", module.eks.cluster_name,
        "--output",       "json",
        "--region", var.region],
      local.aws_profile != "" ? ["--profile", local.aws_profile] : []
    )
    # args = ["eks", "get-token", "--cluster-name", module.eks.cluster_name, "--profile", var.aws_profile]
  }
}

#  Helm provider configuration
provider "helm" {
  kubernetes {
    host                   = module.eks.cluster_endpoint
    cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      args = concat(
        [
          "eks", "get-token",
          "--cluster-name", module.eks.cluster_name,
          "--output",       "json",
          "--region",       var.region,
        ],
        local.aws_profile != "" ? ["--profile", local.aws_profile] : []
      )
      command = "aws"
    }

  }
}

provider "kubectl" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = concat(
      ["eks", "get-token",
        "--cluster-name", module.eks.cluster_name,
        "--output",       "json",
        "--region", var.region],
      local.aws_profile != "" ? ["--profile", local.aws_profile] : []
    )
  }
}


locals {
  cluster_endpoint          = module.eks.cluster_endpoint
  external_private_endpoint = var.api_public_access ? false : true
  cluster_ca_certificate    = base64decode(module.eks.cluster_certificate_authority_data)
  cluster_id                = module.eks.cluster_name
  cluster_region            = var.region
}


# Gets home and current regions
