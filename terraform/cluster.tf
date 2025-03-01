resource "google_container_cluster" "primary" {
  name = var.cluster_name
  location = var.zone

  deletion_protection = false
  remove_default_node_pool = true
  initial_node_count = 1

  release_channel {
    channel = "REGULAR" # --release-channel "regular"
  }

  logging_config { # --logging=SYSTEM,WORKLOAD
    enable_components = [ "SYSTEM_COMPONENTS", "WORKLOADS" ]
  }

  monitoring_config { # --monitoring=SYSTEM,STORAGE,POD,DEPLOYMENT,STATEFULSET,DAEMONSET,HPA,CADVISOR,KUBELET 
    enable_components = [ 
      "SYSTEM_COMPONENTS",
      "STORAGE",
      "POD",
      "DEPLOYMENT",
      "STATEFULSET",
      "DAEMONSET",
      "HPA",
      "CADVISOR",
      "KUBELET"
    ]
    managed_prometheus { # --enable-managed-prometheus
      enabled = true
    }
  }

  networking_mode = "VPC_NATIVE" # --enable-ip-alias
  network = "default" # --network "projects/$GCP_PROJECT/global/networks/default"
  subnetwork = "default" # --subnetwork "projects/$GCP_PROJECT/regions/us-central1/subnetworks/default"
  ip_allocation_policy {} # need to vpc-native cluster
  enable_intranode_visibility = false # --no-enable-intra-node-visibility

  
  private_cluster_config {
    enable_private_nodes = false # --no-enable-master-authorized-networks
    enable_private_endpoint = false # --no-enable-google-cloud-access
  }

  addons_config { # --addons HorizontalPodAutoscaling,HttpLoadBalancing,GcePersistentDiskCsiDriver
    horizontal_pod_autoscaling {
      disabled = false
    }
    http_load_balancing {
      disabled = false
    }
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
  }

  binary_authorization { # --binauthz-evaluation-mode=DISABLED
    evaluation_mode = "DISABLED"
  }

  node_config { # --enable-shielded-nodes
    shielded_instance_config {
      enable_secure_boot = true 
    }
  }

  maintenance_policy {
    recurring_window {
      start_time = "2024-01-01T00:00:00Z"
      end_time   = "2024-01-02T00:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=SA,SU"
    }
  }
}

resource "google_container_node_pool" "primary_nodes" {
  name = "${var.cluster_name}-node-pool"
  location = var.zone # --node-locations "$ZONE"
  cluster = google_container_cluster.primary.name
  node_count = 2


  node_config {
    machine_type = "n2d-standard-4" # --machine-type "n2d-standard-8"
    image_type = "COS_CONTAINERD" # --image-type "COS_CONTAINERD"
    disk_type = "pd-balanced" # --disk-type "pd-balanced"
    disk_size_gb = 100 # --disk-size "100"

    # guest_accelerator { # -- gpu nodes
    #   type  = "nvidia-tesla-t4"
    #   count = 1
    #   gpu_driver_installation_config {
    #     gpu_driver_version = "LATEST"
    #   }
    # }

    # # machine_type = "n1-standard-8" # default = "e2-medium"
    # machine_type = "g2-standard-4" # vs g2-standard-8 (32GB mem)
    

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

}

# Helm Release 설정
resource "helm_release" "vllm" {
  name       = "vllm"
  repository = "https://vllm-project.github.io/production-stack"
  chart      = "vllm-stack"

  values = [
    file(var.setup_yaml)
  ]

  depends_on = [
    google_container_cluster.primary,
    google_container_node_pool.primary_nodes
  ]
}