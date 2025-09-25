# backend.tf

terraform {
    required_providers {
        google = {
            source = "hashicorp/google"
            version = "~> 6.0"
        }

        helm = {
            source  = "hashicorp/helm"
            version = "~> 2.0"
        }
    }
}
