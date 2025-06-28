resource "random_pet" "rg_name" {
  prefix = var.resource_group_name_prefix
}

resource "azurerm_resource_group" "rg" {
  location = var.resource_group_location
  name = random_pet.rg_name.id
}

resource "random_pet" "azurerm_kubernetes_cluster_name" {
  prefix = "cluster"
}

resource "random_pet" "azurerm_kubernetes_cluster_dns_prefix" {
  prefix = "dns"
}

resource "azurerm_kubernetes_cluster" "k8s" {
  location = azurerm_resource_group.rg.location
  name = random_pet.azurerm_kubernetes_cluster_name.id
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix = random_pet.azurerm_kubernetes_cluster_dns_prefix.id

  identity {
    type = "SystemAssigned"
  }

  default_node_pool {
    name = "agentpool"
    vm_size = "standard_d4_v4"
    node_count = var.node_count
  }

  linux_profile {
    admin_username = var.username
    ssh_key {
      key_data = azapi_resource_action.ssh_public_key_gen.output.publicKey
    }
  }
  network_profile {
    network_plugin = "kubenet"
    load_balancer_sku = "standard"
  }
}

resource "azurerm_kubernetes_cluster_node_pool" "gpu_node_pool" {
  name = "gpupool"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.k8s.id
  vm_size = "standard_nc4as_t4_v3"
  node_count = 1

  node_labels = {
    "nvidia.com/gpu" = "present"
  }

  node_taints = ["nvidia.com/gpu=present:NoSchedule"]
}
