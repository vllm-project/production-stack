# cluster.tf

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

  depends_on = [
    time_sleep.wait_60_seconds
  ]
}
