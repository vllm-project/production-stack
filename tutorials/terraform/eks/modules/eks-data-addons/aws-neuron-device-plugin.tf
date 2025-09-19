resource "helm_release" "aws_neuron_device_plugin" {
  count = var.enable_aws_neuron_device_plugin ? 1 : 0

  name                       = try(var.aws_neuron_device_plugin_helm_config["name"], "neuron-helm-chart")
  repository                 = try(var.aws_neuron_device_plugin_helm_config["repository"], null)
  chart                      = try(var.aws_neuron_device_plugin_helm_config["chart"], "oci://public.ecr.aws/neuron/neuron-helm-chart")
  version                    = try(var.aws_neuron_device_plugin_helm_config["version"], "1.1.1")
  timeout                    = try(var.aws_neuron_device_plugin_helm_config["timeout"], 300)
  values                     = try(var.aws_neuron_device_plugin_helm_config["values"], null)
  create_namespace           = try(var.aws_neuron_device_plugin_helm_config["create_namespace"], false)
  namespace                  = try(var.aws_neuron_device_plugin_helm_config["namespace"], "kube-system")
  lint                       = try(var.aws_neuron_device_plugin_helm_config["lint"], false)
  description                = try(var.aws_neuron_device_plugin_helm_config["description"], "")
  repository_key_file        = try(var.aws_neuron_device_plugin_helm_config["repository_key_file"], "")
  repository_cert_file       = try(var.aws_neuron_device_plugin_helm_config["repository_cert_file"], "")
  repository_username        = try(var.aws_neuron_device_plugin_helm_config["repository_username"], "")
  repository_password        = try(var.aws_neuron_device_plugin_helm_config["repository_password"], "")
  verify                     = try(var.aws_neuron_device_plugin_helm_config["verify"], false)
  keyring                    = try(var.aws_neuron_device_plugin_helm_config["keyring"], "")
  disable_webhooks           = try(var.aws_neuron_device_plugin_helm_config["disable_webhooks"], false)
  reuse_values               = try(var.aws_neuron_device_plugin_helm_config["reuse_values"], false)
  reset_values               = try(var.aws_neuron_device_plugin_helm_config["reset_values"], false)
  force_update               = try(var.aws_neuron_device_plugin_helm_config["force_update"], false)
  recreate_pods              = try(var.aws_neuron_device_plugin_helm_config["recreate_pods"], false)
  cleanup_on_fail            = try(var.aws_neuron_device_plugin_helm_config["cleanup_on_fail"], false)
  max_history                = try(var.aws_neuron_device_plugin_helm_config["max_history"], 0)
  atomic                     = try(var.aws_neuron_device_plugin_helm_config["atomic"], false)
  skip_crds                  = try(var.aws_neuron_device_plugin_helm_config["skip_crds"], false)
  render_subchart_notes      = try(var.aws_neuron_device_plugin_helm_config["render_subchart_notes"], true)
  disable_openapi_validation = try(var.aws_neuron_device_plugin_helm_config["disable_openapi_validation"], false)
  wait                       = try(var.aws_neuron_device_plugin_helm_config["wait"], true)
  wait_for_jobs              = try(var.aws_neuron_device_plugin_helm_config["wait_for_jobs"], false)
  dependency_update          = try(var.aws_neuron_device_plugin_helm_config["dependency_update"], false)
  replace                    = try(var.aws_neuron_device_plugin_helm_config["replace"], false)

  postrender {
    binary_path = try(var.aws_neuron_device_plugin_helm_config["postrender"], "")
  }

  dynamic "set" {
    iterator = each_item
    for_each = try(var.aws_neuron_device_plugin_helm_config["set"], [])

    content {
      name  = each_item.value.name
      value = each_item.value.value
      type  = try(each_item.value.type, null)
    }
  }

  dynamic "set_sensitive" {
    iterator = each_item
    for_each = try(var.aws_neuron_device_plugin_helm_config["set_sensitive"], [])

    content {
      name  = each_item.value.name
      value = each_item.value.value
      type  = try(each_item.value.type, null)
    }
  }

}
