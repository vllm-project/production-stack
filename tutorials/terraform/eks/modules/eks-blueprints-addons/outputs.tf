output "argo_rollouts" {
  description = "Map of attributes of the Helm release created"
  value       = module.argo_rollouts
}

output "argo_workflows" {
  description = "Map of attributes of the Helm release created"
  value       = module.argo_workflows
}

output "argocd" {
  description = "Map of attributes of the Helm release created"
  value       = module.argocd
}

output "argo_events" {
  description = "Map of attributes of the Helm release created"
  value       = module.argo_events
}

output "aws_cloudwatch_metrics" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_cloudwatch_metrics
}

output "aws_efs_csi_driver" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_efs_csi_driver
}

output "aws_for_fluentbit" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_for_fluentbit
}

output "aws_fsx_csi_driver" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_fsx_csi_driver
}

output "aws_load_balancer_controller" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_load_balancer_controller
}

output "aws_node_termination_handler" {
  description = "Map of attributes of the Helm release and IRSA created"
  value = merge(
    module.aws_node_termination_handler,
    {
      sqs = module.aws_node_termination_handler_sqs
    }
  )
}

output "aws_privateca_issuer" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_privateca_issuer
}

output "cert_manager" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.cert_manager
}

output "cluster_autoscaler" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.cluster_autoscaler
}

output "cluster_proportional_autoscaler" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.cluster_proportional_autoscaler
}

output "eks_addons" {
  description = "Map of attributes for each EKS addons enabled"
  value       = aws_eks_addon.this
}

output "external_dns" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.external_dns
}

output "external_secrets" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.external_secrets
}

output "fargate_fluentbit" {
  description = "Map of attributes of the configmap and IAM policy created"
  value = {
    configmap            = kubernetes_config_map_v1.aws_logging
    iam_policy           = aws_iam_policy.fargate_fluentbit
    cloudwatch_log_group = aws_cloudwatch_log_group.fargate_fluentbit
  }
}

output "gatekeeper" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.gatekeeper
}

output "ingress_nginx" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.ingress_nginx
}

output "karpenter" {
  description = "Map of attributes of the Helm release and IRSA created"
  value = merge(
    module.karpenter,
    {
      node_instance_profile_name = try(aws_iam_instance_profile.karpenter[0].name, "")
      node_iam_role_arn          = try(aws_iam_role.karpenter[0].arn, "")
      node_iam_role_name         = try(aws_iam_role.karpenter[0].name, "")
      sqs                        = module.karpenter_sqs
    }
  )
}

output "kube_prometheus_stack" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.kube_prometheus_stack
}

output "metrics_server" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.metrics_server
}

output "secrets_store_csi_driver" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.secrets_store_csi_driver
}

output "secrets_store_csi_driver_provider_aws" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.secrets_store_csi_driver_provider_aws
}

output "velero" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.velero
}

output "vpa" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.vpa
}

output "aws_gateway_api_controller" {
  description = "Map of attributes of the Helm release and IRSA created"
  value       = module.aws_gateway_api_controller
}

output "bottlerocket_update_operator" {
  description = "Map of attributes of the Helm release and IRSA created"
  value = {
    operator = module.bottlerocket_update_operator
    crds     = module.bottlerocket_shadow
  }
}

################################################################################
# (Generic) Helm Release
################################################################################

output "helm_releases" {
  description = "Map of attributes of the Helm release created"
  value       = helm_release.this
}

################################################################################
# GitOps Bridge
################################################################################
/*
This output is intended to be used with GitOps when the addons' Helm charts
are going to be installed by a GitOps tool such as ArgoCD or FluxCD.
We guarantee that this output will be maintained any time a new addon is
added or an addon is updated, and new metadata for the Helm chart is needed.
*/
output "gitops_metadata" {
  description = "GitOps Bridge metadata"
  value = merge(
    { for k, v in {
      iam_role_arn    = module.cert_manager.iam_role_arn
      namespace       = local.cert_manager_namespace
      service_account = local.cert_manager_service_account
      } : "cert_manager_${k}" => v if var.enable_cert_manager
    },
    { for k, v in {
      iam_role_arn    = module.cluster_autoscaler.iam_role_arn
      namespace       = local.cluster_autoscaler_namespace
      service_account = local.cluster_autoscaler_service_account
      } : "cluster_autoscaler_${k}" => v if var.enable_cluster_autoscaler
    },
    { for k, v in {
      iam_role_arn    = module.aws_cloudwatch_metrics.iam_role_arn
      namespace       = local.aws_cloudwatch_metrics_namespace
      service_account = local.aws_cloudwatch_metrics_service_account
      } : "aws_cloudwatch_metrics_${k}" => v if var.enable_aws_cloudwatch_metrics
    },
    { for k, v in {
      iam_role_arn               = module.aws_efs_csi_driver.iam_role_arn
      namespace                  = local.aws_efs_csi_driver_namespace
      controller_service_account = local.aws_efs_csi_driver_controller_service_account
      node_service_account       = local.aws_efs_csi_driver_node_service_account
      } : "aws_efs_csi_driver_${k}" => v if var.enable_aws_efs_csi_driver
    },
    { for k, v in {
      iam_role_arn               = module.aws_fsx_csi_driver.iam_role_arn
      namespace                  = local.aws_fsx_csi_driver_namespace
      controller_service_account = local.aws_fsx_csi_driver_controller_service_account
      node_service_account       = local.aws_fsx_csi_driver_node_service_account
      } : "aws_fsx_csi_driver_${k}" => v if var.enable_aws_fsx_csi_driver
    },
    { for k, v in {
      iam_role_arn    = module.aws_privateca_issuer.iam_role_arn
      namespace       = local.aws_privateca_issuer_namespace
      service_account = local.aws_privateca_issuer_service_account
      } : "aws_privateca_issuer_${k}" => v if var.enable_aws_privateca_issuer
    },
    { for k, v in {
      iam_role_arn    = module.external_dns.iam_role_arn
      namespace       = local.external_dns_namespace
      service_account = local.external_dns_service_account
      } : "external_dns_${k}" => v if var.enable_external_dns
    },
    { for k, v in {
      iam_role_arn    = module.external_secrets.iam_role_arn
      namespace       = local.external_secrets_namespace
      service_account = local.external_secrets_service_account
      } : "external_secrets_${k}" => v if var.enable_external_secrets
    },
    { for k, v in {
      iam_role_arn    = module.aws_load_balancer_controller.iam_role_arn
      namespace       = local.aws_load_balancer_controller_namespace
      service_account = local.aws_load_balancer_controller_service_account
      } : "aws_load_balancer_controller_${k}" => v if var.enable_aws_load_balancer_controller
    },
    { for k, v in {
      iam_role_arn    = module.aws_for_fluentbit.iam_role_arn
      namespace       = local.aws_for_fluentbit_namespace
      service_account = local.aws_for_fluentbit_service_account
      log_group_name  = try(aws_cloudwatch_log_group.aws_for_fluentbit[0].name, null)
      } : "aws_for_fluentbit_${k}" => v if var.enable_aws_for_fluentbit && v != null
    },
    { for k, v in {
      iam_role_arn    = module.aws_node_termination_handler.iam_role_arn
      namespace       = local.aws_node_termination_handler_namespace
      service_account = local.aws_node_termination_handler_service_account
      sqs_queue_url   = module.aws_node_termination_handler_sqs.queue_url
      } : "aws_node_termination_handler_${k}" => v if var.enable_aws_node_termination_handler
    },
    { for k, v in {
      iam_role_arn               = module.karpenter.iam_role_arn
      namespace                  = local.karpenter_namespace
      service_account            = local.karpenter_service_account_name
      sqs_queue_name             = module.karpenter_sqs.queue_name
      node_instance_profile_name = local.output_karpenter_node_instance_profile_name
      node_iam_role_name         = try(aws_iam_role.karpenter[0].name, "")
      } : "karpenter_${k}" => v if var.enable_karpenter
    },
    { for k, v in {
      iam_role_arn    = module.velero.iam_role_arn
      namespace       = local.velero_namespace
      service_account = local.velero_service_account
      } : "velero_${k}" => v if var.enable_velero
    },
    { for k, v in {
      iam_role_arn    = module.aws_gateway_api_controller.iam_role_arn
      namespace       = local.aws_gateway_api_controller_namespace
      service_account = local.aws_gateway_api_controller_service_account
      } : "aws_gateway_api_controller_${k}" => v if var.enable_aws_gateway_api_controller
    },
    { for k, v in {
      group_name    = try(var.fargate_fluentbit.cwlog_group, aws_cloudwatch_log_group.fargate_fluentbit[0].name, null)
      stream_prefix = local.fargate_fluentbit_cwlog_stream_prefix
      } : "fargate_fluentbit_log_${k}" => v if var.enable_fargate_fluentbit && v != null
    }
  )
}
