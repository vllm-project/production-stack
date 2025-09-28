################################################################################
# 📦  PROVIDER-LEVEL SETTINGS
################################################################################

variable "region" {
  description = "AWS region where all resources are deployed."
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "AWS profile to use"
  type        = string
  default     = "default"  # Change to your profile name or leave as "default"
}
#  variable "aws_access_key" {
#   sensitive   = true
#  }

#  variable "aws_secret_key" {
#   sensitive   = true
#  }
################################################################################
# 🍿  GLOBAL TAGS & METADATA
################################################################################

variable "tags" {
  description = "Tags applied to all AWS resources."
  type        = map(string)
  default = {
    Project     = "vllm-production-stack"
    Environment = "production"
    Team        = "LLMOps"
    Application = "ai-inference"
    CostCenter  = "AI-1234"
  }
}

################################################################################
# 🌐  NETWORKING – VPC & SUBNETS
################################################################################

variable "create_vpc" {
  description = "Create a new VPC (true) or reuse an existing one (false)."
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "Existing VPC ID (required when create_vpc = false)."
  type        = string
  default     = ""
}

# New‑VPC parameters (ignored when create_vpc = false)
variable "vpc_name" {
  description = "Name for the VPC."
  type        = string
  default     = "vllm-vpc" # Default name for new VPC
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDRs for public subnets."
  type        = list(string)
  default     = ["10.20.101.0/24", "10.20.102.0/24", "10.20.103.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDRs for private subnets."
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24", "10.20.3.0/24"]
}

variable "enable_nat_gateway" {
  type    = bool
  default = true
}

variable "single_nat_gateway" {
  type    = bool
  default = true
}

variable "one_nat_gateway_per_az" {
  type    = bool
  default = false
}

variable "enable_dns_hostnames" {
  type    = bool
  default = true
}

variable "enable_dns_support" {
  type    = bool
  default = true
}

################################################################################
# ⚘️  EKS CLUSTER – CORE SETTINGS
################################################################################

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "vllm-eks"
}

variable "cluster_version" {
  description = "Kubernetes version."
  type        = string
  default     = "1.30"
}

# API endpoint exposure
variable "api_public_access" {
  type    = bool
  default = true
}

variable "api_private_access" {
  type    = bool
  default = true
}

variable "api_public_access_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

# # Networking ranges used by the cluster
variable "pod_cidr" {
  description = "Pod network CIDR."
  type        = string
  default     = "10.244.0.0/16"
}

# variable "service_cidr" {
#   description = "Service CIDR."
#   type        = string
#   default     = "10.96.0.0/16"
# }

# Node groups map (can be empty; built dynamically in main.tf)
# variable "node_groups" {
#   description = "Map of self‑managed or managed node group definitions."
#   type        = any
#   default     = {}
# }

variable "enable_cluster_creator_admin_permissions" {
  description = "Enable admin permissions for the cluster creator."
  type        = bool
  default     = true
}
################################################################################
# 🔒  NETWORKING ADD‑OWNS
################################################################################

variable "calico_version" {
  type    = string
  default = "3.27.2"
}

variable "calico_values_file" {
  type    = string
  default = "modules/eks-data-addons/helm-charts/calico/calico-values.yaml"
}

################################################################################
# 🤖  GPU OPERATOR ADDON
################################################################################

variable "gpu_operator_file" {
  description = "Path to GPU Operator Helm values YAML."
  type        = string
  default     = "modules/llm-stack/helm/gpu/gpu-operator-values.yaml"
}
################################################################################
# 🔐  TLS / CERT‑MANAGER & LET’S ENCRYPT
################################################################################

variable "enable_cert_manager" {
  type    = bool
  default = true
}

variable "enable_cert_manager_cluster_issuer" {
  type    = bool
  default = true
}

variable "letsencrypt_email" {
  type    = string
  default = "admin@example.com"  #CHANGE ME
}

################################################################################
# 📊  OBSERVABILITY – GRAFANA / PROMETHEUS / METRICS
################################################################################

variable "enable_grafana" {
  type    = bool
  default = true
}

variable "enable_prometheus" {
  type    = bool
  default = true
}

variable "enable_metrics_server" {
  type    = bool
  default = true
}

################################################################################
# 🔑  SECRETS MANAGEMENT
################################################################################

variable "enable_external_secrets" {
  type    = bool
  default = true
}

################################################################################
# 💾  STORAGE CSI DRIVERS
################################################################################

variable "enable_ebs_csi_driver" {
  type    = bool
  default = true
}

variable "enable_efs_csi_driver" {
  type    = bool
  default = false
}

variable "enable_efs_storage" {
  description = "Enable EFS storage resources for debugging"
  type        = bool
  default     = false
}

variable "enable_iam_roles" {
  description = "Enable IAM role resources for debugging"
  type        = bool
  default     = false
}

################################################################################
# 🍺  MODULE VERSIONS (optional)
################################################################################

# variable "eks_blueprints_version" {
#   description = "Version of the EKS Blueprints modules."
#   type        = string
#   default     = "v25.0.0"
# }

################################################################################
# ⚙️  NODE‑GROUP STRATEGY
################################################################################

variable "inference_hardware" {
  description = <<EOT
Choose the hardware profile for inference workloads.
• "cpu" → only the default CPU node‑group
• "gpu" → CPU node‑group + a GPU node‑group (g4dn.xlarge, 1 node)
EOT
  type        = string
  default     = "cpu"
  validation {
    condition     = contains(["cpu", "gpu"], lower(var.inference_hardware))
    error_message = "Valid values are \"cpu\" or \"gpu\"."
  }
}

variable "gpu_capacity_type" {
  description = <<EOT
Choose the GPU capacity type for the GPU node-group.
• "ON_DEMAND" → use on-demand GPU instances
• "SPOT" → use spot GPU instances
EOT
  default     = "ON_DEMAND"
  nullable    = false
  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], upper(var.gpu_capacity_type))
    error_message = "Valid values are \"ON_DEMAND\" or \"SPOT\"."
  }
}

variable "gpu_node_instance_types" {
  type    = list(string)
  default = ["g4dn.xlarge"] # g6.2xlarge (8 vCPU, 24 GiB RAM, NVIDIA L4)
}

variable "cpu_node_instance_types" {
  type    = list(string)
  default = ["t3.xlarge"] # t3.medium (2 vCPU, 4 GiB RAM), doesn't work with calico
}

variable "gpu_node_min_size" {
  type    = number
  default = 1
}

variable "gpu_node_max_size" {
  type    = number
  default = 1
}

variable "gpu_node_desired_size" {
  type    = number
  default = 1
}

variable "cpu_node_min_size" {
  type    = number
  default = 1
}

variable "cpu_node_max_size" {
  type    = number
  default = 2
}

variable "cpu_node_desired_size" {
  type    = number
  default = 2
}

################################################################################
# 🎛️  NVIDIA setup selector
################################################################################
variable "nvidia_setup" {
  description = <<EOT
GPU enablement strategy:
  • "plugin"           → installs only the nvidia-device-plugin DaemonSet
  • "operator_custom"  → GPU Operator with your YAML values file
  • "operator_no_driver" → GPU Operator, driver & toolkit pods disabled (map-style set)
EOT
  type        = string
  default     = "plugin"

  validation {
    condition     = contains(["plugin", "operator_custom", "operator_no_driver"], lower(var.nvidia_setup))
    error_message = "Valid values: plugin | operator_custom | operator_no_driver"
  }
}

################################################################################
# 🛠️  ADDITIONAL BLUEPRINT ADDON SETTINGS
################################################################################
variable "enable_lb_ctl" {
  description = "Enable AWS Load Balancer Controller add-on"
  type        = bool
  default     = true
}

variable "enable_external_dns" {
  description = "Enable external-dns operator add-on"
  type        = bool
  default     = false
}

variable "enable_karpenter" {
  description = "Enable Karpenter controller add-on"
  type        = bool
  default     = false
}

variable "enable_kube_prometheus_stack" {
  description = "Enable Kube Prometheus Stack"
  type        = bool
  default     = true
}

variable "enable_cloudwatch" {
  description = "Enable AWS Cloudwatch Metrics add-on for Container Insights"
  type        = bool
  default     = false
}

variable "enable_vpa" {
  description = "Enable Vertical Pod Autoscaler add-on"
  type        = bool
  default     = false
}

################################################################################
# 🧠 VLLM PRODUCTION STACK SETTINGS
################################################################################
variable "enable_vllm" {
  description = "Enable VLLM production stack add-on"
  type        = bool
  default     = false
}

variable "hf_token" {
  description = "Hugging Face access token with model-download scope"
  type        = string
  sensitive   = true
}

variable "cpu_vllm_helm_config" {
  description = "Path to the Helm chart values template for CPU inference."
  type        = string
  default     = "modules/llm-stack/helm/cpu/cpu-tinyllama-light-ingress.tpl"
}

variable "gpu_vllm_helm_config" {
  description = "Path to the Helm chart values template for GPU inference."
  type        = string
  default     = "modules/llm-stack/helm/gpu/gpu-tinyllama-light-ingress.tpl"
}
