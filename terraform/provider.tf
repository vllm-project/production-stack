provider "google" {
  credentials = file(var.credentials_file)
  project = var.project
  zone = var.zone
}

provider "helm" {
  kubernetes {
    host = "https://${google_container_cluster.primary.endpoint}"
    token = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(google_container_cluster.primary.master_auth[0].cluster_ca_certificate)
    config_path = "~/.kube/config"
  }
}

data "google_client_config" "default" {}

# $ kubectl config use-context minikube
# Switched to context "minikube".

# $ kubectl config current-context
# minikube

# kubectl config delete-context minikube
# kubectl config delete-user NAME
# kubectl config delete-cluster NAME