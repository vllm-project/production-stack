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

variable "cluster_name" {
  description = "gke cluster name"
  type = string
  default = "production-stack"
}