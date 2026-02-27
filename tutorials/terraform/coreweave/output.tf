# output "Stack_Info" {
#   value = "Built with ❤️ by @Cloudthrill"
# }

# output "cluster_name" {
#   value = coreweave_cks_cluster.k8s.name
# }

# # CoreWeave endpoint is hostname only; you already learned the hard way 🙂
# output "cluster_endpoint" {
#   value = "https://${coreweave_cks_cluster.k8s.api_server_endpoint}"
# }

# output "org_id" {
#   value = var.org_id
# }

# output "cluster_id" {
#   value = coreweave_cks_cluster.k8s.id
# }

# output "vllm_config" {
#   value = var.enable_vllm ? var.gpu_vllm_helm_config : null
# }
#############################################
# Networking (CoreWeave VPC)
#############################################
# VPC Outputs
# output "vpc_id" {
#   description = "Created VPC ID"
#   value       = coreweave_networking_vpc.k8s.id
# }

# output "vpc_name" {
#   description = "Created VPC name"
#   value       = coreweave_networking_vpc.k8s.name
# }

# output "vpc_zone" {
#   description = "VPC Zone"
#   value       = coreweave_networking_vpc.k8s.zone
# }

# # Optional: echo the prefixes you configured (pods/services/lb)
# output "vpc_prefixes" {
#   description = "VPC prefixes configured on the VPC"
#   value = { for prefix in coreweave_networking_vpc.k8s.vpc_prefixes : prefix.name => prefix.value }
# }

# output "vpc_host_prefix" {
#   description = "VPC Host Prefix"
#   value       = coreweave_networking_vpc.k8s.host_prefix # deprecated
# }

#############################################
# NodePools (CRDs applied via kubectl_manifest)
#############################################

# output "gpu_nodepool_name" {
#   description = "GPU NodePool Name"
#   value       = var.enable_nodepool_gpu ? kubectl_manifest.nodepool_gpu["gpu"].name : null
# }

# NodePool Outputs
# output "cpu_nodepool_name" {
#   description = "CPU NodePool Name"
#   value       = var.enable_nodepool_cpu ? kubectl_manifest.nodepool_cpu["cpu"].name : null
# }

# Instance types (what you requested)
# output "gpu_nodepool_instance" {
#   description = "GPU Instance Type"
#   value       = var.enable_nodepool_gpu ? local.gpu_instance_id : null
# }
# output "cpu_nodepool_instance" {
#   description = "CPU Instance Type"
#   value       = var.enable_nodepool_cpu ? var.cpu_instance_id : null
# }

# Scaling config (what you requested)
# output "cpu_nodepool_scaling" {
#   value = var.enable_nodepool_cpu ? format("[target=%s, min=%s, max=%s, autoscaling=%s]",
#     var.cpu_node_target, var.cpu_node_min, var.cpu_node_max, var.cpu_autoscaling
#   ) : null
# }

# output "gpu_nodepool_scaling" {
#   value = var.enable_nodepool_gpu ? format("[target=%s, min=%s, max=%s, autoscaling=%s]",
#     var.gpu_node_target, var.gpu_node_min, var.gpu_node_max, var.gpu_autoscaling
#   ) : null
# }

# output "z_success_message" {
#   description = "Success message"
#   value       =  <<-EOT

#   ✅ CoreWeave CKS cluster deployed successfully!

#   📋 Next Steps:

#   1. set kubeconfig:
#     export KUBECONFIG="./kubeconfig"

#   2. Get in grafana Dashboard URL:
#     "https://${local.grafana_host}"

#   3. Test vllm endpoint:
#      curl -k "https://${local.vllm_host}/v1/models"

#   📚 Documentation:
#   - CoreWeave Docs: https://docs.coreweave.com
#   - vLLM Production Stack: https://github.com/vllm-project/production-stack

#   EOT
# }

  # 2. Verify cluster access:
  #    cwic nodepool list
  #    cwic nodepool node get gpu-pool
  #    cwic node describe <node-name>
  # 3. Check GPU availability:
  #    kubectl get nodes -o json | jq '.items[].status.capacity'

  # 4. Verify cluster tools:
  #    kubectl get pods -n cert-manager
  #    kubectl get pods -n  traefik

#######################################################
#       Ingress EndPoints
#######################################################

locals {
  base_domain  = "${var.org_id}-${var.cluster_name}.coreweave.app"

  grafana_host = "${var.grafana_host_prefix}.${local.base_domain}"
  vllm_host    = "${var.vllm_host_prefix}.${local.base_domain}"
  # Network string formatting
  net_summary  = join(" | ", [for k, v in { for p in coreweave_networking_vpc.k8s.vpc_prefixes : p.name => p.value } : "${k}: ${v}"])
}

# output "grafana_url" {
#   value = var.enable_monitoring ? "https://${local.grafana_host}" : null
# }

# output "vllm_api_url" {
#   description = "The full HTTPS URL for the vLLM API"
#   value = (var.enable_vllm && var.enable_nodepool_gpu) ? "https://${local.vllm_host}/v1" : null
# }



output "vllm_stack_summary" {
  value = <<-EOT
✅ CoreWeave CKS cluster deployed successfully!

  🚀 VLLM PRODUCTION STACK ON COREWEAVE 🚀
  -----------------------------------------------------------
  ORG ID            : ${var.org_id}
  CLUSTER           : ${coreweave_cks_cluster.k8s.name} (${coreweave_cks_cluster.k8s.id})
  ENDPOINT          : https://${coreweave_cks_cluster.k8s.api_server_endpoint}
  VPC               : ${coreweave_networking_vpc.k8s.name} (${coreweave_networking_vpc.k8s.zone})
  NETWORKING        : ${local.net_summary}

  🖥️  NODEPOOL INFRASTRUCTURE
  -----------------------------------------------------------
  CPU POOL [${var.cpu_instance_id}] : ${var.enable_nodepool_cpu ? kubectl_manifest.nodepool_cpu["cpu"].name : "Disabled"}
  GPU POOL [${local.gpu_instance_id}] : ${var.enable_nodepool_gpu ? kubectl_manifest.nodepool_gpu["gpu"].name : "Disabled"}
  CPU SCALING       : ${var.enable_nodepool_cpu ? format("[target=%s, min=%s, max=%s, autoscaling=%s]", var.cpu_node_target, var.cpu_node_min, var.cpu_node_max, var.cpu_autoscaling) : "N/A"}
  GPU SCALING       : ${var.enable_nodepool_gpu ? format("[target=%s, min=%s, max=%s, autoscaling=%s]", var.gpu_node_target, var.gpu_node_min, var.gpu_node_max, var.gpu_autoscaling) : "N/A"}
  VLLM CONFIG       : ${var.enable_vllm ? "./${var.gpu_vllm_helm_config}" : "None"}

  🌐 ACCESS ENDPOINTS
  -----------------------------------------------------------
  VLLM API          : ${var.enable_vllm ? "https://${local.vllm_host}/v1" : "Disabled"}
  GRAFANA           : ${var.enable_monitoring ? "https://${local.grafana_host}" : "Disabled"}

  🛠️  QUICK START COMMANDS
  -----------------------------------------------------------
  1. Set Context   : export KUBECONFIG="./kubeconfig"
  2. Test Model    : curl -k "https://${local.vllm_host}/v1/models"

  Built with ❤️ by @Cloudthrill
  EOT
}
