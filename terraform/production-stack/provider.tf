# https://github.com/vllm-project/production-stack/compare/main...0xThresh:vllm-production-stack:tutorial-terraform-eks

provider "google" {
  credentials = file(var.credentials_file)
  project = var.project
  zone = var.zone
}

provider "helm" {
  kubernetes {
    # host = "https://${google_container_cluster.primary.endpoint}"
    host = data.terraform_remote_state.local.outputs.gke_cluster_endpoint
    token = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(data.terraform_remote_state.local.outputs.gke_cluster_ca_certificate)
    # config_path = "~/.kube/config"
  }
}

data "google_client_config" "default" {}

data "terraform_remote_state" "local" {
  backend = "local"
  config = {
    path = "../gke-infra/terraform.tfstate"
  }
}

# $ kubectl config use-context minikube
# Switched to context "minikube".

# $ kubectl config current-context
# minikube

# kubectl config delete-context minikube
# kubectl config delete-user NAME
# kubectl config delete-cluster NAME