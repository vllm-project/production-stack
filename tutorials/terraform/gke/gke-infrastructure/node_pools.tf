# node_pools.tf

resource "google_container_node_pool" "primary_nodes" {
  name = "${var.cluster_name}-node-pool"
  location = var.zone
  cluster = google_container_cluster.primary.name
  node_count = 1


  node_config {
    image_type = "COS_CONTAINERD" # --image-type "COS_CONTAINERD"
    disk_type = "pd-balanced" # --disk-type "pd-balanced"
    disk_size_gb = 100 # --disk-size "100"

    machine_type = var.gpu_machine_type

    guest_accelerator { # -- gpu nodes
      type = var.gpu_accelerator_type
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "LATEST"
      }
    }

    metadata = {
      disable-legacy-endpoints = "true"  # # --metadata disable-legacy-endpoints=true
    }
    oauth_scopes = [
      "https://www.googleapis.com/auth/devstorage.read_only",
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring",
      "https://www.googleapis.com/auth/servicecontrol",
      "https://www.googleapis.com/auth/service.management.readonly",
      "https://www.googleapis.com/auth/trace.append"
    ]

    labels = {
      env = var.project
      app = "vllm-inference"
      "nvidia.com/gpu" = "present"
    }

    taint {
      key = "nvidia.com/gpu"
      value = "present"
      effect = "NO_SCHEDULE"
    }

  }

  management {
    auto_repair = true # --enable-autoupgrade
    auto_upgrade = true # --enable-autorepair
  }

  upgrade_settings {
    max_surge = 1 # --max-surge-upgrade 1
    max_unavailable = 0 # --max-unavailable-upgrade 0
  }

  depends_on = [
    google_container_cluster.primary
  ]

}

resource "google_container_node_pool" "mgmt_nodes" {
  name = "${var.cluster_name}-mgmt-pool"
  location = var.zone
  cluster = google_container_cluster.primary.name
  node_count = 1

  node_config {
    image_type = "COS_CONTAINERD"
    disk_type = "pd-balanced"
    disk_size_gb = 50

    machine_type = "e2-standard-4"

    metadata = {
      disable-legacy-endpoints = "true"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/devstorage.read_only",
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring",
      "https://www.googleapis.com/auth/servicecontrol",
      "https://www.googleapis.com/auth/service.management.readonly",
      "https://www.googleapis.com/auth/trace.append"
    ]

    labels = {
      env = var.project
      app = "mgmt-node"
    }
  }

  management {
    auto_repair = true
    auto_upgrade = true
  }

  upgrade_settings {
    max_surge = 1
    max_unavailable = 0
  }

  depends_on = [
    google_container_cluster.primary
  ]
}
