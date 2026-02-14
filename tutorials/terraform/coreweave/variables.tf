###############################################################################
# 🧱  PROVIDER-LEVEL SETTINGS (coreweave)
###############################################################################

variable "org_id" {
  description = "coreweave organization ID (leave empty to use default)"
  type        = string
  default     = ""

  validation {
    condition     = var.org_id != ""
    error_message = "org_id must be set (e.g., cw99) when monitoring/ingress is enabled."
  }
}

variable "cw_token" {
  description = "coreweave access token" # (CW-SECRET-...)
  type = string
  sensitive = true
  nullable = false
  default = null
}

variable "region" {
  description = "coreweave region for the cluster"
  type        = string
  default     = "US-EAST-06"
  nullable    = false         # rejects null
    validation {
    condition     = var.region != ""
    error_message = "Region must not be an empty string."
    }
}

variable "zone" {
  description = "Availability zone (must belong to var.region)"
  type        = string
  default     = "US-EAST-06A"
  nullable = false
     validation {
    condition     = var.zone != ""
    error_message = "Availability Zone must not be an empty string."
    }
  }


###############################################################################
# 🏷️  GLOBAL TAGS & METADATA
###############################################################################

variable "tags" {
  description = "Labels applied to every coreweave resource"
  type        = map(string)
  default = {
    project     = "vllm-production-stack"
    environment = "production"
    team        = "llmops"
    application = "ai-inference"
    costcenter  = "ai-1234"
  }
}

###############################################################################
# 🌐  NETWORKING – VPC & SUBNET
###############################################################################

variable "vpc_name" {
  description = "Name for the VPC network"
  type        = string
  default     = "vllm-vpc"
}

variable "vpc_host_cidr" {
  description = "VPC host_pprefix CIDR."
  type        = string
  default     = "10.192.192.0/18" # default  prefix for US-EAST-06A = 10.192.192.0/18
}

variable "pod_cidr" {
  description = "Primary CIDR for pods"
  type        = string
  default     = "10.244.0.0/16"
}

variable "service_cidr" {
  description = "CIDR block for service IPs"
  type        = string
  default     = "10.96.0.0/16"
}

variable "lb_cidr" {
  description = "CIDR block for load balancer IPs"
  type        = string
  default     = "10.20.0.0/22" # In 10.20.1.0, the last 2 bits of the third octet are 01, not 00
}
###############################################################################
# ⚙️  MANAGED K8s – CORE SETTINGS
###############################################################################

variable "cluster_name" {
  description = "Managed Kubernetes cluster name"
  type        = string
  default     = "vllm-cw-prod"
}

variable "k8s_version" {
  description = "Kubernetes control-plane version"
  type        = string
  default     = "v1.35"
validation {
condition = length(trimspace(var.k8s_version)) > 0
error_message = "k8s_version must not be empty."
}
}

variable "public_endpoint" {
  description = "Expose Kubernetes API on a public IP"
  type        = bool
  default     = true
}

###############################################################################
# 🚀  NODE-POOL (AUTOSCALING)
# NOTE: NodePools are created via Kubernetes CRD (compute.coreweave.com/v1alpha1)
###############################################################################

variable "enable_nodepool_gpu" {
description = "Create the GPU NodePool CR via kubectl provider"
type = bool
default = true
}

variable "enable_nodepool_cpu" {
description = "Create the CPU NodePool CR via kubectl provider"
type = bool
default = true
}

# --------- CPU pool ------------
variable "cpu_instance_id" {
type     = string
nullable = false
default = "cd-gp-i64-erapids"
description = <<-EOT
CoreWeave CPU instance type ID.
Commonly used shapes (alias == instanceType):

- cd-hp-a96-genoa        → AMD Genoa High Performance (9274F, 96 vCPU / 768 GB)
- cd-gp-a192-genoa       → AMD Genoa General Purpose (9454, 192 vCPU / 1536 GB)
- cd-gp-l-a192-genoa     → AMD Genoa General Purpose - High Storage (9454, 192 vCPU / 1536 GB)
- cd-hc-a384-genoa       → AMD Genoa High Core (9654, 384 vCPU / 1536 GB)
- turin-gp               → AMD Turin General Purpose (9655P, 192 vCPU / 1536 GB)
- turin-gp-l             → AMD Turin General Purpose - High Storage (9655P, 192 vCPU / 1536 GB)
- cd-gp-i64-erapids      → Intel Emerald Rapids General Purpose (8562Y+, 64 vCPU / 512 GB)
- cd-gp-i96-icelake      → Intel Ice Lake General Purpose (6342, 96 vCPU / 384 GB)

CPU instance types are intentionally NOT region-gated here. "l" = High Storage i= intell .
Availability and quota are validated by the CoreWeave API at apply time.

Example:
- US-EAST-06A → cd-gp-a192-genoa, turin-gp
- US-EAST-01A → cd-gp-i64-erapids, turin-gp

Reference (official CoreWeave regions & instance availability):
https://docs.coreweave.com/docs/platform/regions/general-access
EOT

}

variable "cpu_nodepool_name" {
  type        = string
  default     = "cpu-pool"
  nullable    = false
}

variable "cpu_autoscaling" {
  type    = bool
  default = true
}

variable "cpu_node_min" {
  type    = number
  default = 1
}

variable "cpu_node_max" {
  type    = number
  default = 2
}

variable "cpu_node_target" {
  type    = number
  default = 1
  validation {
    condition     = var.cpu_node_target >= 0
    error_message = "Target nodes must be >= 0"
  }
}

variable "cpu_scale_down_strategy" {
  description = "Scale down strategy: IdleOnly or PreferIdle"
  type        = string
  default     = "PreferIdle"
  validation {
    condition     = contains(["IdleOnly", "PreferIdle"], var.cpu_scale_down_strategy)
    error_message = "cpu_scale_down_strategy must be 'IdleOnly' or 'PreferIdle'."
  }
}

variable "cpu_disable_unhealthy_node_eviction" {
  description = "Disable unhealthy node eviction"
  type        = bool
  default     = false
}
# ---------------- GPU pool ----------------


variable "gpu_instance_type" {
  description = "GPU hardware alias that will map to the actual GPU instance type"
  type        = string
  default     =  "H100" # "H200" "A100", "B200", "L40" ,"B300" , "L40S" , "GH200" , "GB200" , "RTX 6000"
  nullable    = false          # rejects null
  validation {
    condition     = var.gpu_instance_type != ""
    error_message = "GPU instance type must not be an empty string."
  }

 # Common instance types:
  # gd-8xh100ib-i128  = 8x H100 80GB, InfiniBand, 128GB RAM/GPU (1TB total)
  # gd-8xa100ib-i64   = 8x A100 40GB, InfiniBand, 64GB RAM/GPU (512GB total)
  # gd-8xa100-80ib-i80 = 8x A100 80GB, InfiniBand, 80GB RAM/GPU (640GB total)
  # gd-4xh100ib-i128  = 4x H100 80GB, InfiniBand, 128GB RAM/GPU (512GB total)
}

variable "gpu_nodepool_name" {
description = "NodePool name"
type = string
default = "gpu-pool"
}

variable "gpu_autoscaling" {
  type    = bool
  default = true
}

variable "gpu_node_min" {
  description = "Minimum GPU nodes (zero-scale friendly)"
  type        = number
  default     = 1
}

  variable "gpu_node_max" {
    description = "Maximum GPU nodes"
  type        = number
  default     = 2
}

variable "gpu_node_target" {
  type    = number
  default = 1
    validation {
    condition     = var.gpu_node_target >= 0
    error_message = "Target nodes must be >= 0"
  }
}

# --- labels and annotations
variable "gpu_nodepool_labels" {
  description = "Labels applied to GPU nodes (via nodeLabels in NodePool spec)"
  type        = map(string)
  default = {
    "node-group" = "gpu-pool"
    "workload-type" = "gpu"
    "vllm-node"     = "true"
  }
}

variable "gpu_nodepool_taints" {
  description = "Taints applied to GPU nodes (via nodeTaints in NodePool spec)"
  type = list(object({
    key    = string
    value  = string
    effect = string  # NoSchedule, PreferNoSchedule, or NoExecute
  }))
  default = [
    {
      key    = "nvidia.com/gpu"
      value  = "true"
      effect = "NoSchedule"
    }
  ]
  validation {
    condition = alltrue([
      for t in var.gpu_nodepool_taints :
      contains(["NoSchedule", "PreferNoSchedule", "NoExecute"], t.effect)
    ])
    error_message = "gpu_nodepool_taints.effect must be one of: NoSchedule, PreferNoSchedule, NoExecute."
  }
}

variable "nodepool_gpu_annotations" {
  description = "Annotations applied to GPU nodes (via nodeAnnotations in NodePool spec)"
  type        = map(string)
  default = {
    "managed-by" = "terraform"
  }
}

# --- Lifecycle  options
variable "gpu_scale_down_strategy" {
  description = "Scale down strategy: IdleOnly or PreferIdle"
  type        = string
  default     = "PreferIdle" # "IdleOnly" or "PreferIdle"
  validation {
    condition     = contains(["IdleOnly", "PreferIdle"], var.gpu_scale_down_strategy)
    error_message = "gpu_scale_down_strategy must be 'IdleOnly' or 'PreferIdle'."
  }
}

variable "gpu_disable_unhealthy_node_eviction" {
  description = "Disable unhealthy node eviction"
  type        = bool
  default     = true
}

 variable "gpu_compute_class" {
  description = "Node compute class"
  type        = string
  default     = "default" # "default" or "spot"
}
# variable "gpu_update_strategy" {
#   description = "Node configuration update strategy (Manual only)"
#   type        = string
#   default     = "Manual"
# }

###############################################################################
#  🛜 ENDPOINTS
###############################################################################

variable "grafana_host_prefix" {
  type    = string
  default = "grafana"
}

variable "vllm_host_prefix" {
  type    = string
  default = "vllm"
}
###############################################################################
# 🔐  CORE ADDONS + OBSERVABILITY (ON/OFF SWITCHES)
###############################################################################

variable "enable_cert_manager" {
  type    = bool
  default = true
}

variable "enable_metrics_server" {
  type    = bool
  default = true
}

variable "enable_monitoring" {
  type    = bool
  default = true
}

variable "grafana_admin_password" {
  type      = string
  sensitive = true
  default   = "admin1234" # Change me!
}

variable "prometheus_scrape_interval" {
  description = "Prometheus scrape interval"
  type        = string
  default     = "1m"
}

variable "prometheus_retention" {
  description = "Prometheus data retention period"
  type        = string
  default     = "15d"
}

variable "prometheus_pv_size" {
  description = "Prometheus persistent volume size"
  type        = string
  default     = "25Gi"
}

variable "use_letsencrypt_staging" {
  description = "Use Let's Encrypt staging environment (for testing)"
  type        = bool
  default     = false
}

variable "letsencrypt_email" {
  type    = string
  default =  "info@cloudthrill.ca"  # "admin@example.com"  #  forbidden domain "example.com"
    validation {
    condition     = can(regex("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", var.letsencrypt_email))
    error_message = "The letsencrypt_email variable must be a valid email address (doesn't allow *@example.com )."
  }
}
###############################################################################
# 🧠  VLLM STACK SETTINGS
###############################################################################

variable "vllm_namespace" {
  description = "Kubernetes namespace for vLLM deployment"
  type        = string
  default     = "vllm"
}

variable "enable_vllm" {
  description = "Deploy VLLM inference stack via Helm"
  type        = bool
  default     = false
}

variable "hf_token" {
  description = "Hugging Face token for model download"
  type        = string
  sensitive   = true
  default     = ""
      validation {
    condition     = var.hf_token != ""
    error_message = "Hugging Face token must not be empty."
    }
}

variable "gpu_vllm_helm_config" {
  description = "Path to GPU VLLM Helm values template"
  type        = string
  default     = "config/llm-stack/helm/gpu/gpu-gpt-oss-20-cw.tpl"
  # "config/llm-stack/helm/gpu/gpu-llama-light-ingress-cw.tpl"
  # "config/llm-stack/helm/gpu/gpu-gpt-qwn-gem-glm-cw.tpl"
}
