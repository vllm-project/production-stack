###############################################################################
# 🧱  PROVIDER-LEVEL SETTINGS (Nebius)
###############################################################################

variable "neb_project_id" {
  description = "Nebius project ID (leave empty to use CLI profile default)"
  type        = string
  default     = ""
}

variable "region" {
  description = "Nebius region for the cluster"
  type        = string
  default     = "eu-north1"
  nullable    = false          # rejects null
    validation {
    condition     = var.region != ""
    error_message = "Region must not be an empty string."
    }
}

variable "zone" {
  description = "Availability zone (must belong to var.region)"
  type        = string
  default     = "eu-north1-a"
}

variable "ops_email" {
  description = "Email address for budget alert notifications"
  type        = string
  default     = "info@example.com"
 # check email regex validation for the variable in terraform
  validation {
    condition     = can(regex("^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", var.ops_email))
    error_message = "The ops_email variable must be a valid email address."
  }
}

variable "neb_profile" {
  description = "nebius profile to use"
  type        = string
  default     = "cloudthrill"  # Change to your profile name of leave empty to use default
}
###############################################################################
# 🏷️  GLOBAL TAGS & METADATA
###############################################################################

variable "tags" {
  description = "Labels applied to every Nebius resource"
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

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "subnetwork_cidr" {
  description = "Primary CIDR for the subnetwork"
  type        = string
  default     = "10.20.1.0/24"
}

variable "subnetwork2_cidr" {
  description = "Primary CIDR for the subnetwork"
  type        = string
  default     = "10.20.2.0/24"
}

variable "subnetwork3_cidr" {
  description = "Primary CIDR for the subnetwork"
  type        = string
  default     = "10.20.3.0/24"
}
variable "service_cidr" {
  description = "CIDR block for service IPs"
  type        = string
  default     = "10.96.0.0/16"
}

###############################################################################
# ⚙️  MANAGED K8s – CORE SETTINGS
###############################################################################

variable "cluster_name" {
  description = "Managed Kubernetes cluster name"
  type        = string
  default     = "vllm-neb-gpu"
}

variable "k8s_version" {
  description = "Kubernetes control-plane version"
  type        = string
  default     = "1.30"
}

variable "public_endpoint" {
  description = "Expose Kubernetes API on a public IP"
  type        = bool
  default     = true
}

variable "cpu_node_min" {
  description = "Minimum CPU nodes (zero-scale friendly)"
  type        = number
  default     = 1
}

variable "cpu_node_max" {
  description = "Maximum CPU nodes"
  type        = number
  default     = 2
}

###############################################################################
# 🚀  GPU NODE-GROUP (AUTOSCALING)
###############################################################################

variable "gpu_node_min" {
  description = "Minimum GPU nodes (zero-scale friendly)"
  type        = number
  default     = 0
}

variable "gpu_node_max" {
  description = "Maximum GPU nodes"
  type        = number
  default     = 3
}

variable "gpu_platform" {
  description = "GPU hardware platform"
  type        = string
  default     =  "gpu-l40s-d" # "gpu-l40s-a" "gpu-h100-sxm", "gpu-h200-sxm", "gpu-b200-sxm"
  nullable    = false          # rejects null
  validation {
    condition     = var.gpu_platform != ""
    error_message = "GPU platform must not be an empty string."
  }
}

variable "gpu_preset" {
  description = "Preset (vCPU/RAM/GPU) for GPU nodes"
  type        = string
  default     = "1gpu-8vcpu-32gb"# "8vcpu-64gb-1xa100-80gb"
}



variable "cpu_disk_size_gb" {
  type        = number
  default     = 128
  description = "OS disk size for CPU nodes"
}
variable "gpu_disk_size_gb" {
  type        = number
  default     = 128
  description = "OS disk size for GPU nodes"
}

# OS Disk Type variables
variable "cpu_disk_type" {
  default    = "NETWORK_SSD"

  validation {
    condition     = contains(["UNSPECIFIED", "NETWORK_SSD", "NETWORK_HDD", "NETWORK_SSD_IO_M3"], upper(var.cpu_disk_type))
    error_message = "Valid values are \"UNSPECIFIED\", \"NETWORK_SSD\", \"NETWORK_HDD\", or \"NETWORK_SSD_IO_M3\"."
  }
}

variable "gpu_disk_type" {
  default    = "NETWORK_SSD"

  validation {
    condition     = contains(["UNSPECIFIED", "NETWORK_SSD", "NETWORK_HDD", "NETWORK_SSD_IO_M3"], upper(var.gpu_disk_type))
    error_message = "Valid values are \"UNSPECIFIED\", \"NETWORK_SSD\", \"NETWORK_HDD\", or \"NETWORK_SSD_IO_M3\"."
  }
}

###############################################################################
# 💾  SHARED READ-WRITE-MANY FILESYSTEM
###############################################################################

variable "shared_fs_size_tb" {
  description = "Size of the shared filesystem in TiB"
  type        = number
  default     = 1
}

variable "shared_fs_type" {
  description = "Underlying disk type for the filesystem"
  type        = string
  default     = "network-ssd"
}

###############################################################################
# 🔐  CORE ADDONS + OBSERVABILITY (ON/OFF SWITCHES)
###############################################################################

variable "enable_cert_manager" {
  type    = bool
  default = true
}

variable "grafana_admin_password" {
  type      = string
  sensitive = true
  default   = "admin1234"
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


# variable "tenant_name" {
#   description = "Nebius tenant name (required if Grafana is enabled)"
#   type        = string
#   default     = ""

#   validation {
#     condition     = var.enable_loki ? var.tenant_name != "" : true
#     error_message = "tenant_name must be provided when enable_loki is true."
#   }
# }

variable "letsencrypt_email" {
  type    = string
  default =  "info@cloudthrill.ca"  # "admin@example.com"  #  forbidden domain "example.com"
}
###############################################################################
# 🧠  VLLM STACK SETTINGS
###############################################################################

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
}

variable "gpu_vllm_helm_config" {
  description = "Path to GPU VLLM Helm values template"
  type        = string
  default     = "config/llm-stack/helm/gpu/gpu-tinyllama-light-ingress-nebius.tpl"
}
