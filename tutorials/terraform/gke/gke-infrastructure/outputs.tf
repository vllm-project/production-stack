# outputs.tf

output "gke_cluster_ca_certificate" {
  description = "GKE cluster CA certificate"
  value = google_container_cluster.primary.master_auth[0].cluster_ca_certificate
}

output "gke_cluster_endpoint" {
  description = "GKE cluster endpoint"
  value = google_container_cluster.primary.endpoint
}

output "gke_cluster_name" {
  description = "GKE cluster name"
  value = google_container_cluster.primary.name
}
