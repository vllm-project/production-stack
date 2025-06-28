resource "random_pet" "ssh_key_name" {
  prefix = "ssh"
  separator = ""
}

resource "azapi_resource" "ssh_public_key" {
  type = "Microsoft.Compute/sshPublicKeys@2022-11-01"
  name = random_pet.ssh_key_name.id
  location = azurerm_resource_group.rg.location
  parent_id = azurerm_resource_group.rg.id
}

resource "azapi_resource_action" "ssh_public_key_gen" {
  type = "Microsoft.Compute/sshPublicKeys@2022-11-01"
  resource_id = azapi_resource.ssh_public_key.id
  action = "generateKeyPair"
  method = "POST"

  response_export_values = ["publicKey", "privateKey"]
}

output "key_data" {
  value = azapi_resource_action.ssh_public_key_gen.output.publicKey
}

output "ssh_private_key" {
  description = "The private SSH key for accessing cluster nodes. Save this to a file to SSH into the nodes."
  value       = azapi_resource_action.ssh_public_key_gen.output.privateKey
  sensitive   = true
}
