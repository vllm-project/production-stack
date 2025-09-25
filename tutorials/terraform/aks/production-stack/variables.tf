variable "setup_yaml" {
  type = string
  description = "production-stack setup yaml"
  default = "../production_stack_specification.yaml"
}

variable "prom_stack_yaml" {
  type = string
  description = "default prom stack yaml file"
  default = "../../../../observability/kube-prom-stack.yaml"
}

variable "prom_adapter_yaml" {
  type = string
  description = "default prom adapter yaml file"
  default = "../../../../observability/prom-adapter.yaml"
}
