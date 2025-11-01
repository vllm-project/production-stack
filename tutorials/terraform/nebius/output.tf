output "Stack_Info" {
  value = "Built with ❤️ by @Cloudthrill"
}

output "kubeconfig_cmd" {
  value = "nebius mk8s cluster get-credentials ${nebius_mk8s_v1_cluster.k8s.id} --external"
}


output "project_id" {
  value = local.project_id
}
output "cluster_id" {
  value = nebius_mk8s_v1_cluster.k8s.id
}
output "cluster_endpoint" {
  value = try(nebius_mk8s_v1_cluster.k8s.control_plane[0].endpoints[0].public_endpoint[0].address, "private-only")
}


# Outputs
output "vpc_id" {
  description = "Created VPC ID"
  value       = nebius_vpc_v1_network.k8s.id
}

output "vpc_name" {
  description = "Created VPC name"
  value       = nebius_vpc_v1_network.k8s.name
}

output "subnet_id" {
  description = "Created Subnet ID"
  value       = nebius_vpc_v1_subnet.k8s.id
}

output "subnet_cidr" {
  description = "Subnet CIDR"
  value       = nebius_vpc_v1_subnet.k8s.ipv4_private_pools
}

output "success_message" {
  description = "Success message"
  value       = "VPC and subnet created successfully! Profile authentication is working."
}

output "gpu_node" {
  description = "GPU Node Group Name"
  value       = nebius_mk8s_v1_node_group.gpu.name
}

output "gpu_node_platform" {
  description = "GPU Platform"
  value       =  nebius_mk8s_v1_node_group.gpu.template.resources.platform
}

output "gpu_node_preset" {
  description = "GPU Preset"
  value       = nebius_mk8s_v1_node_group.gpu.template.resources.preset
}

output "cpu_node" {
  description = "CPU Node Group Name"
  value       = nebius_mk8s_v1_node_group.cpu.name
}

output "cpu_node_platform" {
  description = "CPU Platform"
  value       =  nebius_mk8s_v1_node_group.cpu.template.resources.platform
}

output "cpu_node_preset" {
  description = "CPU Preset"
  value       = nebius_mk8s_v1_node_group.cpu.template.resources.preset
}

output "gpu_node_gpu_settings" {
  description = "info"
  value = nebius_mk8s_v1_node_group.gpu.template.gpu_settings
}

output "gpu_node_scaling" {
  value = format("[%s x , Max %s]",
                 nebius_mk8s_v1_node_group.gpu.autoscaling.min_node_count,
                 nebius_mk8s_v1_node_group.gpu.autoscaling.max_node_count)
}

output "gpu_nodegroup_id" {
  description = "GPU Node Group ID"
  value       = nebius_mk8s_v1_node_group.gpu.id
}
#######################################################
#       Ingress EndPoints
#######################################################

output "grafana_url" {
  value = "https://${data.kubernetes_ingress_v1.grafana.spec[0].rule[0].host}"
}

# # Output the complete API URL
output "vllm_api_url" {
  description = "The full HTTPS URL for the vLLM API"
  value = var.enable_vllm ? (
    local.vllm_ingress_host != "pending" && local.vllm_ingress_host != "not-deployed"
    ? "https://${local.vllm_ingress_host}/v1"
    : local.vllm_ingress_host
  ) : null
  depends_on = [helm_release.vllm_stack]
}
