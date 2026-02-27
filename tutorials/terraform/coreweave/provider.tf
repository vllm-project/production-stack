terraform {
  required_providers {
    coreweave = {
      source = "coreweave/coreweave"
      version = "0.10.1"
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
# ============================================================================
# CoreWeave Provider
# ============================================================================

provider "coreweave" {
  # there no possibility to use CWIC CLI profile - as of now.
  token = var.cw_token #use export "CW-SECRET-XXXXXXXXXXXXX"
}

# ============================================================================
# Exec Command for Kubernetes Authentication
# ============================================================================

locals {
  # CoreWeave cwic generates kubeconfig at: ~/.kube/config-<OrgName>-<ClusterName>
  # Send DOWN arrow key (\x1B[B) + Enter (\r) to select option 2 non-interactively
  # Extract token and cleanup the temporary kubeconfig file
  exec_cmd = <<-EOC
    echo -ne '\x1B[B\r' | cwic cluster auth ${coreweave_cks_cluster.k8s.name} >/dev/null 2>&1;
    KUBECONFIG_FILE="$HOME/.kube/config-*-${coreweave_cks_cluster.k8s.name}";
    token=$(grep -A 5 "token:" $KUBECONFIG_FILE | head -1 | awk '{print $2}');
    rm -f $KUBECONFIG_FILE;
    jq -n --arg token "$token" '{apiVersion: "client.authentication.k8s.io/v1", kind: "ExecCredential", status: {token: $token}}'
  EOC
}

# ============================================================================
# Kubernetes Provider Configuration
# ============================================================================
provider "kubernetes" {

  host     = "https://${coreweave_cks_cluster.k8s.api_server_endpoint}"

  insecure = true

  exec {
    api_version = "client.authentication.k8s.io/v1"
    command     = "bash"
    args        = ["-c", local.exec_cmd]
  }
}


# ============================================================================
# Helm Provider Configuration
# ============================================================================
provider "helm" {
  kubernetes = {
    host                   = "https://${coreweave_cks_cluster.k8s.api_server_endpoint}"
    insecure = true
    exec = {
      api_version = "client.authentication.k8s.io/v1"
      command     = "bash"
      args        = ["-c", local.exec_cmd]
    }
  }
}
# ============================================================================
# kubectl Provider Configuration
# ============================================================================

provider "kubectl" {
  host                   = "https://${coreweave_cks_cluster.k8s.api_server_endpoint}"
  load_config_file       = false
insecure = true
  exec {
    api_version = "client.authentication.k8s.io/v1"
    command     = "bash"
    args        = ["-lc", local.exec_cmd]
  }
}
