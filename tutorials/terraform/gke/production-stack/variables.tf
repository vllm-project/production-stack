# variables.tf

variable "credentials_file" {
  description = "google credentials file"
  type = string
  default = "../credentials.json"
}

variable "project" {
  description = "project name"
  type = string
  default = "optimap-438115"
}

variable "zone" {
  description = "zone name"
  type = string
  default = "us-central1-a"
}

variable "setup_yaml" {
  description = "default yaml file"
  type = string
  default = "../production_stack_specification.yaml"
}


variable "prom_stack_yaml" {
  description = "default prom stack yaml file"
  type = string
  default = "../../../../observability/kube-prom-stack.yaml"
}

variable "prom_adapter_yaml" {
  description = "default prom adapter yaml file"
  type = string
  default = "../../../../observability/prom-adapter.yaml"
}
