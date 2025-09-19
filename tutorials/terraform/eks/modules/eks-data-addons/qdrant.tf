locals {
  qdrant_name       = "qdrant"
  qdrant_repository = "https://qdrant.github.io/qdrant-helm"
  qdrant_version    = "0.7.6"

  qdrant_namespace  = try(var.qdrant_helm_config["namespace"], local.qdrant_name)
  qdrant_set_values = []

  qdrant_default_values = <<-EOT
replicaCount: 3

env:
  - name: QDRANT__TELEMETRY_DISABLED
    value: true

service:
  type: LoadBalancer

resources:
  limits:
    cpu: 200m
    memory: 1Gi
  requests:
    cpu: 200m
    memory: 1Gi

persistence:
  storageClassName: gp2

metrics:
  serviceMonitor:
    enabled: true

apiKey: false

EOT

  qdrant_merged_values_yaml = yamlencode(merge(
    yamldecode(local.qdrant_default_values),
    try(yamldecode(var.qdrant_helm_config.values[0]), {})
  ))

}

resource "helm_release" "qdrant" {
  count = var.enable_qdrant ? 1 : 0

  name                       = try(var.qdrant_helm_config["name"], local.qdrant_name)
  repository                 = try(var.qdrant_helm_config["repository"], local.qdrant_repository)
  chart                      = try(var.qdrant_helm_config["chart"], local.qdrant_name)
  version                    = try(var.qdrant_helm_config["version"], local.qdrant_version)
  timeout                    = try(var.qdrant_helm_config["timeout"], 300)
  values                     = [local.qdrant_merged_values_yaml]
  create_namespace           = try(var.qdrant_helm_config["create_namespace"], true)
  namespace                  = local.qdrant_namespace
  lint                       = try(var.qdrant_helm_config["lint"], false)
  description                = try(var.qdrant_helm_config["description"], "")
  repository_key_file        = try(var.qdrant_helm_config["repository_key_file"], "")
  repository_cert_file       = try(var.qdrant_helm_config["repository_cert_file"], "")
  repository_username        = try(var.qdrant_helm_config["repository_username"], "")
  repository_password        = try(var.qdrant_helm_config["repository_password"], "")
  verify                     = try(var.qdrant_helm_config["verify"], false)
  keyring                    = try(var.qdrant_helm_config["keyring"], "")
  disable_webhooks           = try(var.qdrant_helm_config["disable_webhooks"], false)
  reuse_values               = try(var.qdrant_helm_config["reuse_values"], false)
  reset_values               = try(var.qdrant_helm_config["reset_values"], false)
  force_update               = try(var.qdrant_helm_config["force_update"], false)
  recreate_pods              = try(var.qdrant_helm_config["recreate_pods"], false)
  cleanup_on_fail            = try(var.qdrant_helm_config["cleanup_on_fail"], false)
  max_history                = try(var.qdrant_helm_config["max_history"], 0)
  atomic                     = try(var.qdrant_helm_config["atomic"], false)
  skip_crds                  = try(var.qdrant_helm_config["skip_crds"], false)
  render_subchart_notes      = try(var.qdrant_helm_config["render_subchart_notes"], true)
  disable_openapi_validation = try(var.qdrant_helm_config["disable_openapi_validation"], false)
  wait                       = try(var.qdrant_helm_config["wait"], true)
  wait_for_jobs              = try(var.qdrant_helm_config["wait_for_jobs"], false)
  dependency_update          = try(var.qdrant_helm_config["dependency_update"], false)
  replace                    = try(var.qdrant_helm_config["replace"], false)

  postrender {
    binary_path = try(var.qdrant_helm_config["postrender"], "")
  }

  dynamic "set" {
    iterator = each_item
    for_each = distinct(concat(try(var.qdrant_helm_config.set, []), local.qdrant_set_values))

    content {
      name  = each_item.value.name
      value = each_item.value.value
      type  = try(each_item.value.type, null)
    }
  }

  dynamic "set_sensitive" {
    iterator = each_item
    for_each = try(var.qdrant_helm_config["set_sensitive"], [])

    content {
      name  = each_item.value.name
      value = each_item.value.value
      type  = try(each_item.value.type, null)
    }
  }
}
