terraform {
  required_providers {
    nebius = {
      source  = "terraform-provider.storage.eu-north1.nebius.cloud/nebius/nebius"
      version = ">= 0.5.55"
    }
        kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.10"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.15"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.19.0"
    }
    local = {
      source  = "hashicorp/local"
      version = ">= 2.5"
    }

  }

}

provider "nebius" {
  # To use CLI profile - check nested schema documentation
  # The provider supports profile {} but exact syntax needs verification
  # from: https://docs.nebius.com/terraform-provider/reference

  # Uncomment and configure based on actual schema:
  profile = {
    name = var.neb_profile != "" ? var.neb_profile : ""  # Replace with your actual profile name
  }

  # Alternative authentication methods:
  # 1. IAM Token:
  # token = var.token

  # 2. Service Account:
  # service_account = {
  #   account_id       = "serviceaccount-e00a0b1c**********"
  #   public_key_id    = "publickey-e00z9y8x**********"
  #   private_key_file = "~/.nebius/authkey/private.pem"
  # }
}

locals {
  exec_cmd = <<-EOC
    tok=$(nebius iam get-access-token --format json${var.neb_profile != "" ? " --profile ${var.neb_profile}" : ""});
    jq -n --arg token "$tok" '{apiVersion: "client.authentication.k8s.io/v1", kind: "ExecCredential", status: {token: $token}}'
  EOC
}
# Kubernetes provider configuration
provider "kubernetes" {
  host                   = "${nebius_mk8s_v1_cluster.k8s.status.control_plane.endpoints.public_endpoint}"
  cluster_ca_certificate = nebius_mk8s_v1_cluster.k8s.status.control_plane.auth.cluster_ca_certificate

  exec {
    api_version = "client.authentication.k8s.io/v1"
    command     = "bash"
    args        = ["-c", local.exec_cmd]
  }
}

# Helm provider configuration
provider "helm" {
  kubernetes = {
  host                   = "${nebius_mk8s_v1_cluster.k8s.status.control_plane.endpoints.public_endpoint}"
  cluster_ca_certificate = nebius_mk8s_v1_cluster.k8s.status.control_plane.auth.cluster_ca_certificate

  exec = {
    api_version = "client.authentication.k8s.io/v1"
    command     = "bash"
    args        = ["-c", local.exec_cmd]
  }
  }
}

# kubectl provider configuration
provider "kubectl" {
  host                   = "${nebius_mk8s_v1_cluster.k8s.status.control_plane.endpoints.public_endpoint}"
  cluster_ca_certificate = nebius_mk8s_v1_cluster.k8s.status.control_plane.auth.cluster_ca_certificate

  exec {
    api_version = "client.authentication.k8s.io/v1"
    command     = "bash"
    args        = ["-c", local.exec_cmd]
  }
}
