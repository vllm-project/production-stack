# backend.tf

terraform {
    required_providers {
        google = {
            source = "hashicorp/google"
            version = "~> 6.0"
        }
    }
}
