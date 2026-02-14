################################################################################
#  Author: Kosseila HD (@CloudThrill)  --  re-tooled for CoreWeave
#  License: MIT
#  Date: Q1 2026
#  Description: IaC for vLLM-production-stack on CoreWeave CKS (Managed K8s) – GPU-only, autoscaling,
#                , inference, and observability all in one place.
#  Full code will be merged on the official vllm-production-stack project: https://github.com/vllm-project/production-stack
#  Part of the CloudThrill implementation contribution to the VLLM community.
#  https://cloudthrill.ca
################################################################################

###############################################################################
# 0.  CoreWeave project & token helpers
###############################################################################

######################
# 0.1 platform locals
######################

  locals {
  # US-EAST-06A -> US-EAST-06, RNO2A -> RNO2, US-WEST-09B -> US-WEST-09
  region_from_zone = replace(upper(var.zone), "/[A-Z]$/", "")

  # 1) Global alias -> CoreWeave instanceType ID (deduped)
  gpu_alias_to_instance_type = {
    H100    = "gd-8xh100ib-i128"
    H200    = "gd-8xh200ib-i128"
    A100    = "gd-8xa100-i128"
    L40     = "gd-8xl40-i128"
    L40S    = "gd-8xl40s-i128"
    GH200   = "gd-1xgh200"
    B200    = "b200-8x"
    GB200   = "gb200-4x"
    GB300   = "gb300-4x"
    RTX6000 = "rtxp6000-8x"
  }

  # 2) Region -> allowed GPU aliases
  region_gpu_aliases = {
    "US-EAST-01"     = ["GB200", "H200", "H100"]
    "US-EAST-02"     = ["GB200", "H200", "L40"]
    "US-EAST-04"     = ["H200", "H100", "RTX6000", "L40S", "L40", "GH200", "A100"]
    "US-EAST-06"     = ["H100", "RTX6000"]
    "US-EAST-08"     = ["GB200", "H200"]
    "US-EAST-13"     = ["GB200", "B200", "RTX6000"]
    "US-EAST-14"     = ["RTX6000"]
    "US-CENTRAL-07"  = ["B200"]
    "US-WEST-01"     = ["GB300", "GB200", "B200", "H100"]
    "RNO2"           = ["H100", "L40", "GH200", "A100"]
    "US-WEST-04"     = ["H200", "H100", "RTX6000"]
    "US-WEST-09"     = ["B200", "H100", "RTX6000"]
    "EU-SOUTH-03"    = ["H200"]
    "EU-SOUTH-04"    = ["RTX6000", "GB200"]
  }

  selected_gpu_alias = upper(var.gpu_instance_type)

  allowed_gpu_aliases = sort(
    lookup(local.region_gpu_aliases, local.region_from_zone, [])
  )

  # Final resolved CoreWeave instanceType ID
  gpu_instance_id = (
    contains(local.allowed_gpu_aliases, local.selected_gpu_alias)
    ? local.gpu_alias_to_instance_type[local.selected_gpu_alias]
    : null
  )
}


###############################################################################
# 1.  Create the cluster
###############################################################################

resource "coreweave_cks_cluster" "k8s" {
  name                   = var.cluster_name # "vllm-gpu-cluster"
  version                = var.k8s_version # "1.35"
  zone                   = var.zone
  vpc_id                 = coreweave_networking_vpc.k8s.id
  public                 = var.public_endpoint
  pod_cidr_name          = "pod-cidr"
  service_cidr_name      = "service-cidr"
  internal_lb_cidr_names = ["lb-cidr"]
  audit_policy           = filebase64("${path.module}/config/manifests/audit-policy.yaml")
  # oidc = {
  #   ca              = filebase64("${path.module}/example-ca.crt")
  #   client_id       = "kbyuFDidLLm280LIwVFiazOqjO3ty8KH"
  #   groups_claim    = "read-only"
  #   groups_prefix   = "cw"
  #   issuer_url      = "https://samples.auth0.com/"
  #   required_claim  = ""
  #   signing_algs    = ["SIGNING_ALGORITHM_RS256"]
  #   username_claim  = "user_id"
  #   username_prefix = "cw"
  # }
  # authn_webhook = {
  #   ca     = filebase64("${path.module}/example-ca.crt")
  #   server = "https://samples.auth0.com/"
  # }
  # authz_webhook = {
  #   ca     = filebase64("${path.module}/example-ca.crt")
  #   server = "https://samples.auth0.com/"
  # }
}



###############################################################################
# CPU Node Group (for system workloads)
###############################################################################

resource "kubectl_manifest" "nodepool_cpu" {
  for_each = var.enable_nodepool_cpu ? toset(["cpu"]) : toset([])

  yaml_body = templatefile("${path.module}/config/manifests/nodepool-cpu.tpl",
    {
      nodepool_name = var.cpu_nodepool_name
      instance_type = var.cpu_instance_id  # CoreWeave generic 16-core SKU
      autoscaling   = var.cpu_autoscaling
      target_nodes  = var.cpu_node_target
      min_nodes     = var.cpu_node_min
      max_nodes     = var.cpu_node_max
      scale_down    = var.cpu_scale_down_strategy               # ←   enum: IdleOnly, PreferIdle
      disable_evict = var.cpu_disable_unhealthy_node_eviction   # ←   bool
    }
  )

# instance.spec.nodeConfigurationUpdateStrategy must NOT have additional properties
  depends_on = [coreweave_cks_cluster.k8s, terraform_data.wait_for_apiserver_dns]
}

###############################################################################
# GPU Node Group (H100 - modify as needed)
###############################################################################
resource "kubectl_manifest" "nodepool_gpu" {
  for_each = var.enable_nodepool_gpu ? toset(["gpu"]) : toset([])

  lifecycle {
    precondition {
      condition     = local.gpu_instance_id != null
      error_message = "GPU '${var.gpu_instance_type}' is not available in region '${local.region_from_zone}' (from zone '${var.zone}'). Allowed GPUs: ${join(", ", local.allowed_gpu_aliases)}."
    }
  }

yaml_body = templatefile(
    "${path.module}/config/manifests/nodepool-gpu.tpl",
    {
      nodepool_name    = var.gpu_nodepool_name
      instance_type    = local.gpu_instance_id
    #  compute_class    = var.gpu_compute_class   # default or spot
      autoscaling      = var.gpu_autoscaling
      target_nodes     = var.gpu_node_target
      min_nodes        = var.gpu_node_min
      max_nodes        = var.gpu_node_max
      scale_down       = var.gpu_scale_down_strategy               # ←   enum: IdleOnly, PreferIdle
      disable_evict    = var.gpu_disable_unhealthy_node_eviction   # ←   bool
      node_labels      = var.gpu_nodepool_labels    # Pass raw map
      node_taints      = var.gpu_nodepool_taints    # Pass raw list
    }
  )


  depends_on = [
    coreweave_cks_cluster.k8s,
    kubectl_manifest.nodepool_cpu
  ]
}

###############################################################################
# 6.  Kubeconfig file for local usage
###############################################################################
# data "coreweave_client_config" "default" {}
resource "null_resource" "write_kubeconfig" {
  triggers = {
    cluster_name = coreweave_cks_cluster.k8s.name
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command = <<-EOC
      set -euo pipefail
      CLUSTER="${coreweave_cks_cluster.k8s.name}"

      echo -ne '\x1B[B\r' | cwic cluster auth "$CLUSTER" >/dev/null 2>&1

      SRC="$(ls -t "$HOME"/.kube/config-*-"$CLUSTER" 2>/dev/null | head -n 1)"
      if [ -z "$${SRC:-}" ] || [ ! -f "$SRC" ]; then
        echo "cwic did not produce kubeconfig for cluster $CLUSTER" >&2
        exit 1
      fi

      cp "$SRC" "${path.module}/kubeconfig"
      chmod 0600 "${path.module}/kubeconfig"
    EOC
  }

  depends_on = [coreweave_cks_cluster.k8s]
}


############################### WORKFLOW ######################################
# source .env_vars
# terraform init
# terraform plan
# terraform apply
# export KUBECONFIG=$PWD/kubeconfig
# kubectl get nodes
