terraform {
  required_version = ">=1.0"

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }
}

provider "helm" {
  kubernetes {
    config_path = "${path.module}/../azurek8s"
  }
}
