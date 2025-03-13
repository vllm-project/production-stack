# providers.tf

provider "google" {
  credentials = file(var.credentials_file)
  project = var.project
  zone = var.zone
}

provider "helm" {
  kubernetes {
    host = data.terraform_remote_state.local.outputs.gke_cluster_endpoint
    token = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(data.terraform_remote_state.local.outputs.gke_cluster_ca_certificate)
  }
}

data "google_client_config" "default" {}

data "terraform_remote_state" "local" {
  backend = "local"
  config = {
    path = "../gke-infrastructure/terraform.tfstate"
  }
}
