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

variable "gcp_services" {
    description = "List of GCP services required for GKE project"
    type = list(string)
    default = [
        # Core GKE-related services
        "container.googleapis.com",       # Kubernetes Engine API
        "compute.googleapis.com",         # Compute Engine API
        "iam.googleapis.com",             # Identity and Access Management API
        "monitoring.googleapis.com",      # Cloud Monitoring API
        "logging.googleapis.com",         # Cloud Logging API
        "cloudtrace.googleapis.com",      # Cloud Trace API
        "stackdriver.googleapis.com",     # Stackdriver API

        # Networking related services
        "servicenetworking.googleapis.com",  # Service Networking API
        "networkmanagement.googleapis.com",  # Network Management API

        # Storage related services
        "storage-api.googleapis.com",     # Cloud Storage API
        "artifactregistry.googleapis.com", # Artifact Registry API
    ]
}

variable "gpu_machine_type" {
  description = "gpu node pool machine type"
  type = string
  default = "g2-standard-8" # (8vpu, 32GB mem)
}

variable "gpu_accelerator_type" {
  description = "gpu node pool gpu type"
  type = string
  default = "nvidia-l4"
}
