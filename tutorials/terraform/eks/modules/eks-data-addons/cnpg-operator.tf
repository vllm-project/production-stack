locals {
  cnpg_operator_name = "cnpg"
  cnpg_chart_name    = "cloudnative-pg"
  cnpg_operator_repo = "https://cloudnative-pg.github.io/charts"
  cnpg_chart_version = try(var.cnpg_operator_helm_config["version"], "0.17.0")
}
resource "helm_release" "cnpg_operator" {
  count = var.enable_cnpg_operator ? 1 : 0

  name                       = try(var.cnpg_operator_helm_config["name"], local.cnpg_operator_name)
  repository                 = try(var.cnpg_operator_helm_config["repository"], local.cnpg_operator_repo)
  chart                      = try(var.cnpg_operator_helm_config["chart"], local.cnpg_chart_name)
  version                    = local.cnpg_chart_version
  timeout                    = try(var.cnpg_operator_helm_config["timeout"], 300)
  values                     = try(var.cnpg_operator_helm_config["values"], null)
  create_namespace           = try(var.cnpg_operator_helm_config["create_namespace"], true)
  namespace                  = try(var.cnpg_operator_helm_config["namespace"], "cnpg-system")
  lint                       = try(var.cnpg_operator_helm_config["lint"], false)
  description                = try(var.cnpg_operator_helm_config["description"], "")
  repository_key_file        = try(var.cnpg_operator_helm_config["repository_key_file"], "")
  repository_cert_file       = try(var.cnpg_operator_helm_config["repository_cert_file"], "")
  repository_username        = try(var.cnpg_operator_helm_config["repository_username"], "")
  repository_password        = try(var.cnpg_operator_helm_config["repository_password"], "")
  verify                     = try(var.cnpg_operator_helm_config["verify"], false)
  keyring                    = try(var.cnpg_operator_helm_config["keyring"], "")
  disable_webhooks           = try(var.cnpg_operator_helm_config["disable_webhooks"], false)
  reuse_values               = try(var.cnpg_operator_helm_config["reuse_values"], false)
  reset_values               = try(var.cnpg_operator_helm_config["reset_values"], false)
  force_update               = try(var.cnpg_operator_helm_config["force_update"], false)
  recreate_pods              = try(var.cnpg_operator_helm_config["recreate_pods"], false)
  cleanup_on_fail            = try(var.cnpg_operator_helm_config["cleanup_on_fail"], false)
  max_history                = try(var.cnpg_operator_helm_config["max_history"], 0)
  atomic                     = try(var.cnpg_operator_helm_config["atomic"], false)
  skip_crds                  = try(var.cnpg_operator_helm_config["skip_crds"], false)
  render_subchart_notes      = try(var.cnpg_operator_helm_config["render_subchart_notes"], true)
  disable_openapi_validation = try(var.cnpg_operator_helm_config["disable_openapi_validation"], false)
  wait                       = try(var.cnpg_operator_helm_config["wait"], true)
  wait_for_jobs              = try(var.cnpg_operator_helm_config["wait_for_jobs"], false)
  dependency_update          = try(var.cnpg_operator_helm_config["dependency_update"], false)
  replace                    = try(var.cnpg_operator_helm_config["replace"], false)

  postrender {
    binary_path = try(var.cnpg_operator_helm_config["postrender"], "")
  }

  dynamic "set" {
    iterator = each_item
    for_each = try(var.cnpg_operator_helm_config["set"], [])

    content {
      name  = each_item.value.name
      value = each_item.value.value
      type  = try(each_item.value.type, null)
    }
  }

  dynamic "set_sensitive" {
    iterator = each_item
    for_each = try(var.cnpg_operator_helm_config["set_sensitive"], [])

    content {
      name  = each_item.value.name
      value = each_item.value.value
      type  = try(each_item.value.type, null)
    }
  }

}
