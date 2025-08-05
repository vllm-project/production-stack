data "azurerm_kubernetes_cluster" "credentials_file" {
  name = azurerm_kubernetes_cluster.k8s.name
  resource_group_name = azurerm_resource_group.rg.name
}

resource "local_file" "azure-config" {
  content  = data.azurerm_kubernetes_cluster.credentials_file.kube_config_raw
  filename = var.azure_kube_config
}
