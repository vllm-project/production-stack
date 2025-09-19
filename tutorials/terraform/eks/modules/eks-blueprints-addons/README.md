# Amazon EKS Blueprints Addons

Terraform module to deploy Kubernetes addons on Amazon EKS clusters.

## Usage

```hcl
module "eks_blueprints_addons" {
  source = "aws-ia/eks-blueprints-addons/aws"
  version = "~> 1.0" #ensure to update this to the latest/desired version

  cluster_name      = module.eks.cluster_name
  cluster_endpoint  = module.eks.cluster_endpoint
  cluster_version   = module.eks.cluster_version
  oidc_provider_arn = module.eks.oidc_provider_arn

  eks_addons = {
    aws-ebs-csi-driver = {
      most_recent = true
    }
    coredns = {
      most_recent = true
    }
    vpc-cni = {
      most_recent = true
    }
    kube-proxy = {
      most_recent = true
    }
  }

  enable_aws_load_balancer_controller    = true
  enable_cluster_proportional_autoscaler = true
  enable_karpenter                       = true
  enable_kube_prometheus_stack           = true
  enable_metrics_server                  = true
  enable_external_dns                    = true
  enable_cert_manager                    = true
  cert_manager_route53_hosted_zone_arns  = ["arn:aws:route53:::hostedzone/XXXXXXXXXXXXX"]

  tags = {
    Environment = "dev"
  }
}

module "eks" {
  source = "terraform-aws-modules/eks/aws"

  cluster_name    = "my-cluster"
  cluster_version = "1.29"

  ... truncated for brevity
}
```

## Support & Feedback

> [!IMPORTANT]
> EKS Blueprints for Terraform is maintained by AWS Solution Architects. It is not part of an AWS
> service and support is provided as a best-effort by the EKS Blueprints community. To provide feedback,
> please use the [issues templates](https://github.com/aws-ia/terraform-aws-eks-blueprints-addons/issues)
> provided. If you are interested in contributing to EKS Blueprints, see the
> [Contribution guide](https://github.com/aws-ia/terraform-aws-eks-blueprints-addons/blob/main/.github/CONTRIBUTING.md).

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.0 |
| <a name="requirement_helm"></a> [helm](#requirement\_helm) | >= 2.9, < 3.0 |
| <a name="requirement_kubernetes"></a> [kubernetes](#requirement\_kubernetes) | >= 2.20 |
| <a name="requirement_random"></a> [random](#requirement\_random) | >= 3.6 |
| <a name="requirement_time"></a> [time](#requirement\_time) | >= 0.9 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | >= 5.0 |
| <a name="provider_helm"></a> [helm](#provider\_helm) | >= 2.9, < 3.0 |
| <a name="provider_kubernetes"></a> [kubernetes](#provider\_kubernetes) | >= 2.20 |
| <a name="provider_random"></a> [random](#provider\_random) | >= 3.6 |
| <a name="provider_time"></a> [time](#provider\_time) | >= 0.9 |

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_argo_events"></a> [argo\_events](#module\_argo\_events) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_argo_rollouts"></a> [argo\_rollouts](#module\_argo\_rollouts) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_argo_workflows"></a> [argo\_workflows](#module\_argo\_workflows) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_argocd"></a> [argocd](#module\_argocd) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_cloudwatch_metrics"></a> [aws\_cloudwatch\_metrics](#module\_aws\_cloudwatch\_metrics) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_efs_csi_driver"></a> [aws\_efs\_csi\_driver](#module\_aws\_efs\_csi\_driver) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_for_fluentbit"></a> [aws\_for\_fluentbit](#module\_aws\_for\_fluentbit) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_fsx_csi_driver"></a> [aws\_fsx\_csi\_driver](#module\_aws\_fsx\_csi\_driver) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_gateway_api_controller"></a> [aws\_gateway\_api\_controller](#module\_aws\_gateway\_api\_controller) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_load_balancer_controller"></a> [aws\_load\_balancer\_controller](#module\_aws\_load\_balancer\_controller) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_node_termination_handler"></a> [aws\_node\_termination\_handler](#module\_aws\_node\_termination\_handler) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_aws_node_termination_handler_sqs"></a> [aws\_node\_termination\_handler\_sqs](#module\_aws\_node\_termination\_handler\_sqs) | terraform-aws-modules/sqs/aws | 4.0.1 |
| <a name="module_aws_privateca_issuer"></a> [aws\_privateca\_issuer](#module\_aws\_privateca\_issuer) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_bottlerocket_shadow"></a> [bottlerocket\_shadow](#module\_bottlerocket\_shadow) | aws-ia/eks-blueprints-addon/aws | ~> 1.1.1 |
| <a name="module_bottlerocket_update_operator"></a> [bottlerocket\_update\_operator](#module\_bottlerocket\_update\_operator) | aws-ia/eks-blueprints-addon/aws | ~> 1.1.1 |
| <a name="module_cert_manager"></a> [cert\_manager](#module\_cert\_manager) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_cluster_autoscaler"></a> [cluster\_autoscaler](#module\_cluster\_autoscaler) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_cluster_proportional_autoscaler"></a> [cluster\_proportional\_autoscaler](#module\_cluster\_proportional\_autoscaler) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_external_dns"></a> [external\_dns](#module\_external\_dns) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_external_secrets"></a> [external\_secrets](#module\_external\_secrets) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_gatekeeper"></a> [gatekeeper](#module\_gatekeeper) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_ingress_nginx"></a> [ingress\_nginx](#module\_ingress\_nginx) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_karpenter"></a> [karpenter](#module\_karpenter) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_karpenter_sqs"></a> [karpenter\_sqs](#module\_karpenter\_sqs) | terraform-aws-modules/sqs/aws | 4.0.1 |
| <a name="module_kube_prometheus_stack"></a> [kube\_prometheus\_stack](#module\_kube\_prometheus\_stack) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_metrics_server"></a> [metrics\_server](#module\_metrics\_server) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_secrets_store_csi_driver"></a> [secrets\_store\_csi\_driver](#module\_secrets\_store\_csi\_driver) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_secrets_store_csi_driver_provider_aws"></a> [secrets\_store\_csi\_driver\_provider\_aws](#module\_secrets\_store\_csi\_driver\_provider\_aws) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_velero"></a> [velero](#module\_velero) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |
| <a name="module_vpa"></a> [vpa](#module\_vpa) | aws-ia/eks-blueprints-addon/aws | 1.1.1 |

## Resources

| Name | Type |
|------|------|
| [aws_autoscaling_group_tag.aws_node_termination_handler](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/autoscaling_group_tag) | resource |
| [aws_autoscaling_lifecycle_hook.aws_node_termination_handler](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/autoscaling_lifecycle_hook) | resource |
| [aws_cloudformation_stack.usage_telemetry](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudformation_stack) | resource |
| [aws_cloudwatch_event_rule.aws_node_termination_handler](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.karpenter](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_target.aws_node_termination_handler](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.karpenter](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_log_group.aws_for_fluentbit](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.fargate_fluentbit](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_eks_addon.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_addon) | resource |
| [aws_iam_instance_profile.karpenter](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_instance_profile) | resource |
| [aws_iam_policy.fargate_fluentbit](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_role.karpenter](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy_attachment.additional](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.karpenter](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [helm_release.this](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [kubernetes_config_map_v1.aws_logging](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/config_map_v1) | resource |
| [kubernetes_config_map_v1_data.aws_for_fluentbit_containerinsights](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/config_map_v1_data) | resource |
| [kubernetes_namespace_v1.aws_observability](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/namespace_v1) | resource |
| [random_bytes.this](https://registry.terraform.io/providers/hashicorp/random/latest/docs/resources/bytes) | resource |
| [time_sleep.this](https://registry.terraform.io/providers/hashicorp/time/latest/docs/resources/sleep) | resource |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_eks_addon_version.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/eks_addon_version) | data source |
| [aws_iam_policy_document.aws_efs_csi_driver](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.aws_for_fluentbit](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.aws_fsx_csi_driver](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.aws_gateway_api_controller](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.aws_load_balancer_controller](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.aws_node_termination_handler](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.aws_privateca_issuer](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.cert_manager](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.cluster_autoscaler](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.external_dns](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.external_secrets](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.fargate_fluentbit](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.karpenter](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.karpenter_assume_role](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.velero](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_argo_events"></a> [argo\_events](#input\_argo\_events) | Argo Events add-on configuration values | `any` | `{}` | no |
| <a name="input_argo_rollouts"></a> [argo\_rollouts](#input\_argo\_rollouts) | Argo Rollouts add-on configuration values | `any` | `{}` | no |
| <a name="input_argo_workflows"></a> [argo\_workflows](#input\_argo\_workflows) | Argo Workflows add-on configuration values | `any` | `{}` | no |
| <a name="input_argocd"></a> [argocd](#input\_argocd) | ArgoCD add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_cloudwatch_metrics"></a> [aws\_cloudwatch\_metrics](#input\_aws\_cloudwatch\_metrics) | Cloudwatch Metrics add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_efs_csi_driver"></a> [aws\_efs\_csi\_driver](#input\_aws\_efs\_csi\_driver) | EFS CSI Driver add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_for_fluentbit"></a> [aws\_for\_fluentbit](#input\_aws\_for\_fluentbit) | AWS Fluentbit add-on configurations | `any` | `{}` | no |
| <a name="input_aws_for_fluentbit_cw_log_group"></a> [aws\_for\_fluentbit\_cw\_log\_group](#input\_aws\_for\_fluentbit\_cw\_log\_group) | AWS Fluentbit CloudWatch Log Group configurations | `any` | `{}` | no |
| <a name="input_aws_fsx_csi_driver"></a> [aws\_fsx\_csi\_driver](#input\_aws\_fsx\_csi\_driver) | FSX CSI Driver add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_gateway_api_controller"></a> [aws\_gateway\_api\_controller](#input\_aws\_gateway\_api\_controller) | AWS Gateway API Controller add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_load_balancer_controller"></a> [aws\_load\_balancer\_controller](#input\_aws\_load\_balancer\_controller) | AWS Load Balancer Controller add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_node_termination_handler"></a> [aws\_node\_termination\_handler](#input\_aws\_node\_termination\_handler) | AWS Node Termination Handler add-on configuration values | `any` | `{}` | no |
| <a name="input_aws_node_termination_handler_asg_arns"></a> [aws\_node\_termination\_handler\_asg\_arns](#input\_aws\_node\_termination\_handler\_asg\_arns) | List of Auto Scaling group ARNs that AWS Node Termination Handler will monitor for EC2 events | `list(string)` | `[]` | no |
| <a name="input_aws_node_termination_handler_sqs"></a> [aws\_node\_termination\_handler\_sqs](#input\_aws\_node\_termination\_handler\_sqs) | AWS Node Termination Handler SQS queue configuration values | `any` | `{}` | no |
| <a name="input_aws_privateca_issuer"></a> [aws\_privateca\_issuer](#input\_aws\_privateca\_issuer) | AWS PCA Issuer add-on configurations | `any` | `{}` | no |
| <a name="input_bottlerocket_shadow"></a> [bottlerocket\_shadow](#input\_bottlerocket\_shadow) | Bottlerocket Update Operator CRDs configuration values | `any` | `{}` | no |
| <a name="input_bottlerocket_update_operator"></a> [bottlerocket\_update\_operator](#input\_bottlerocket\_update\_operator) | Bottlerocket Update Operator add-on configuration values | `any` | `{}` | no |
| <a name="input_cert_manager"></a> [cert\_manager](#input\_cert\_manager) | cert-manager add-on configuration values | `any` | `{}` | no |
| <a name="input_cert_manager_route53_hosted_zone_arns"></a> [cert\_manager\_route53\_hosted\_zone\_arns](#input\_cert\_manager\_route53\_hosted\_zone\_arns) | List of Route53 Hosted Zone ARNs that are used by cert-manager to create DNS records | `list(string)` | <pre>[<br/>  "arn:aws:route53:::hostedzone/*"<br/>]</pre> | no |
| <a name="input_cluster_autoscaler"></a> [cluster\_autoscaler](#input\_cluster\_autoscaler) | Cluster Autoscaler add-on configuration values | `any` | `{}` | no |
| <a name="input_cluster_endpoint"></a> [cluster\_endpoint](#input\_cluster\_endpoint) | Endpoint for your Kubernetes API server | `string` | n/a | yes |
| <a name="input_cluster_name"></a> [cluster\_name](#input\_cluster\_name) | Name of the EKS cluster | `string` | n/a | yes |
| <a name="input_cluster_proportional_autoscaler"></a> [cluster\_proportional\_autoscaler](#input\_cluster\_proportional\_autoscaler) | Cluster Proportional Autoscaler add-on configurations | `any` | `{}` | no |
| <a name="input_cluster_version"></a> [cluster\_version](#input\_cluster\_version) | Kubernetes `<major>.<minor>` version to use for the EKS cluster (i.e.: `1.24`) | `string` | n/a | yes |
| <a name="input_create_delay_dependencies"></a> [create\_delay\_dependencies](#input\_create\_delay\_dependencies) | Dependency attribute which must be resolved before starting the `create_delay_duration` | `list(string)` | `[]` | no |
| <a name="input_create_delay_duration"></a> [create\_delay\_duration](#input\_create\_delay\_duration) | The duration to wait before creating resources | `string` | `"30s"` | no |
| <a name="input_create_kubernetes_resources"></a> [create\_kubernetes\_resources](#input\_create\_kubernetes\_resources) | Create Kubernetes resource with Helm or Kubernetes provider | `bool` | `true` | no |
| <a name="input_eks_addons"></a> [eks\_addons](#input\_eks\_addons) | Map of EKS add-on configurations to enable for the cluster. Add-on name can be the map keys or set with `name` | `any` | `{}` | no |
| <a name="input_eks_addons_timeouts"></a> [eks\_addons\_timeouts](#input\_eks\_addons\_timeouts) | Create, update, and delete timeout configurations for the EKS add-ons | `map(string)` | `{}` | no |
| <a name="input_enable_argo_events"></a> [enable\_argo\_events](#input\_enable\_argo\_events) | Enable Argo Events add-on | `bool` | `false` | no |
| <a name="input_enable_argo_rollouts"></a> [enable\_argo\_rollouts](#input\_enable\_argo\_rollouts) | Enable Argo Rollouts add-on | `bool` | `false` | no |
| <a name="input_enable_argo_workflows"></a> [enable\_argo\_workflows](#input\_enable\_argo\_workflows) | Enable Argo workflows add-on | `bool` | `false` | no |
| <a name="input_enable_argocd"></a> [enable\_argocd](#input\_enable\_argocd) | Enable Argo CD Kubernetes add-on | `bool` | `false` | no |
| <a name="input_enable_aws_cloudwatch_metrics"></a> [enable\_aws\_cloudwatch\_metrics](#input\_enable\_aws\_cloudwatch\_metrics) | Enable AWS Cloudwatch Metrics add-on for Container Insights | `bool` | `false` | no |
| <a name="input_enable_aws_efs_csi_driver"></a> [enable\_aws\_efs\_csi\_driver](#input\_enable\_aws\_efs\_csi\_driver) | Enable AWS EFS CSI Driver add-on | `bool` | `false` | no |
| <a name="input_enable_aws_for_fluentbit"></a> [enable\_aws\_for\_fluentbit](#input\_enable\_aws\_for\_fluentbit) | Enable AWS for FluentBit add-on | `bool` | `false` | no |
| <a name="input_enable_aws_fsx_csi_driver"></a> [enable\_aws\_fsx\_csi\_driver](#input\_enable\_aws\_fsx\_csi\_driver) | Enable AWS FSX CSI Driver add-on | `bool` | `false` | no |
| <a name="input_enable_aws_gateway_api_controller"></a> [enable\_aws\_gateway\_api\_controller](#input\_enable\_aws\_gateway\_api\_controller) | Enable AWS Gateway API Controller add-on | `bool` | `false` | no |
| <a name="input_enable_aws_load_balancer_controller"></a> [enable\_aws\_load\_balancer\_controller](#input\_enable\_aws\_load\_balancer\_controller) | Enable AWS Load Balancer Controller add-on | `bool` | `false` | no |
| <a name="input_enable_aws_node_termination_handler"></a> [enable\_aws\_node\_termination\_handler](#input\_enable\_aws\_node\_termination\_handler) | Enable AWS Node Termination Handler add-on | `bool` | `false` | no |
| <a name="input_enable_aws_privateca_issuer"></a> [enable\_aws\_privateca\_issuer](#input\_enable\_aws\_privateca\_issuer) | Enable AWS PCA Issuer | `bool` | `false` | no |
| <a name="input_enable_bottlerocket_update_operator"></a> [enable\_bottlerocket\_update\_operator](#input\_enable\_bottlerocket\_update\_operator) | Enable Bottlerocket Update Operator add-on | `bool` | `false` | no |
| <a name="input_enable_cert_manager"></a> [enable\_cert\_manager](#input\_enable\_cert\_manager) | Enable cert-manager add-on | `bool` | `false` | no |
| <a name="input_enable_cluster_autoscaler"></a> [enable\_cluster\_autoscaler](#input\_enable\_cluster\_autoscaler) | Enable Cluster autoscaler add-on | `bool` | `false` | no |
| <a name="input_enable_cluster_proportional_autoscaler"></a> [enable\_cluster\_proportional\_autoscaler](#input\_enable\_cluster\_proportional\_autoscaler) | Enable Cluster Proportional Autoscaler | `bool` | `false` | no |
| <a name="input_enable_eks_fargate"></a> [enable\_eks\_fargate](#input\_enable\_eks\_fargate) | Identifies whether or not respective addons should be modified to support deployment on EKS Fargate | `bool` | `false` | no |
| <a name="input_enable_external_dns"></a> [enable\_external\_dns](#input\_enable\_external\_dns) | Enable external-dns operator add-on | `bool` | `false` | no |
| <a name="input_enable_external_secrets"></a> [enable\_external\_secrets](#input\_enable\_external\_secrets) | Enable External Secrets operator add-on | `bool` | `false` | no |
| <a name="input_enable_fargate_fluentbit"></a> [enable\_fargate\_fluentbit](#input\_enable\_fargate\_fluentbit) | Enable Fargate FluentBit add-on | `bool` | `false` | no |
| <a name="input_enable_gatekeeper"></a> [enable\_gatekeeper](#input\_enable\_gatekeeper) | Enable Gatekeeper add-on | `bool` | `false` | no |
| <a name="input_enable_ingress_nginx"></a> [enable\_ingress\_nginx](#input\_enable\_ingress\_nginx) | Enable Ingress Nginx | `bool` | `false` | no |
| <a name="input_enable_karpenter"></a> [enable\_karpenter](#input\_enable\_karpenter) | Enable Karpenter controller add-on | `bool` | `false` | no |
| <a name="input_enable_kube_prometheus_stack"></a> [enable\_kube\_prometheus\_stack](#input\_enable\_kube\_prometheus\_stack) | Enable Kube Prometheus Stack | `bool` | `false` | no |
| <a name="input_enable_metrics_server"></a> [enable\_metrics\_server](#input\_enable\_metrics\_server) | Enable metrics server add-on | `bool` | `false` | no |
| <a name="input_enable_secrets_store_csi_driver"></a> [enable\_secrets\_store\_csi\_driver](#input\_enable\_secrets\_store\_csi\_driver) | Enable CSI Secrets Store Provider | `bool` | `false` | no |
| <a name="input_enable_secrets_store_csi_driver_provider_aws"></a> [enable\_secrets\_store\_csi\_driver\_provider\_aws](#input\_enable\_secrets\_store\_csi\_driver\_provider\_aws) | Enable AWS CSI Secrets Store Provider | `bool` | `false` | no |
| <a name="input_enable_velero"></a> [enable\_velero](#input\_enable\_velero) | Enable Kubernetes Dashboard add-on | `bool` | `false` | no |
| <a name="input_enable_vpa"></a> [enable\_vpa](#input\_enable\_vpa) | Enable Vertical Pod Autoscaler add-on | `bool` | `false` | no |
| <a name="input_external_dns"></a> [external\_dns](#input\_external\_dns) | external-dns add-on configuration values | `any` | `{}` | no |
| <a name="input_external_dns_route53_zone_arns"></a> [external\_dns\_route53\_zone\_arns](#input\_external\_dns\_route53\_zone\_arns) | List of Route53 zones ARNs which external-dns will have access to create/manage records (if using Route53) | `list(string)` | `[]` | no |
| <a name="input_external_secrets"></a> [external\_secrets](#input\_external\_secrets) | External Secrets add-on configuration values | `any` | `{}` | no |
| <a name="input_external_secrets_kms_key_arns"></a> [external\_secrets\_kms\_key\_arns](#input\_external\_secrets\_kms\_key\_arns) | List of KMS Key ARNs that are used by Secrets Manager that contain secrets to mount using External Secrets | `list(string)` | <pre>[<br/>  "arn:aws:kms:*:*:key/*"<br/>]</pre> | no |
| <a name="input_external_secrets_secrets_manager_arns"></a> [external\_secrets\_secrets\_manager\_arns](#input\_external\_secrets\_secrets\_manager\_arns) | List of Secrets Manager ARNs that contain secrets to mount using External Secrets | `list(string)` | <pre>[<br/>  "arn:aws:secretsmanager:*:*:secret:*"<br/>]</pre> | no |
| <a name="input_external_secrets_ssm_parameter_arns"></a> [external\_secrets\_ssm\_parameter\_arns](#input\_external\_secrets\_ssm\_parameter\_arns) | List of Systems Manager Parameter ARNs that contain secrets to mount using External Secrets | `list(string)` | <pre>[<br/>  "arn:aws:ssm:*:*:parameter/*"<br/>]</pre> | no |
| <a name="input_fargate_fluentbit"></a> [fargate\_fluentbit](#input\_fargate\_fluentbit) | Fargate fluentbit add-on config | `any` | `{}` | no |
| <a name="input_fargate_fluentbit_cw_log_group"></a> [fargate\_fluentbit\_cw\_log\_group](#input\_fargate\_fluentbit\_cw\_log\_group) | AWS Fargate Fluentbit CloudWatch Log Group configurations | `any` | `{}` | no |
| <a name="input_gatekeeper"></a> [gatekeeper](#input\_gatekeeper) | Gatekeeper add-on configuration | `any` | `{}` | no |
| <a name="input_helm_releases"></a> [helm\_releases](#input\_helm\_releases) | A map of Helm releases to create. This provides the ability to pass in an arbitrary map of Helm chart definitions to create | `any` | `{}` | no |
| <a name="input_ingress_nginx"></a> [ingress\_nginx](#input\_ingress\_nginx) | Ingress Nginx add-on configurations | `any` | `{}` | no |
| <a name="input_karpenter"></a> [karpenter](#input\_karpenter) | Karpenter add-on configuration values | `any` | `{}` | no |
| <a name="input_karpenter_enable_instance_profile_creation"></a> [karpenter\_enable\_instance\_profile\_creation](#input\_karpenter\_enable\_instance\_profile\_creation) | Determines whether Karpenter will be allowed to create the IAM instance profile (v1beta1) or if Terraform will (v1alpha1) | `bool` | `true` | no |
| <a name="input_karpenter_enable_spot_termination"></a> [karpenter\_enable\_spot\_termination](#input\_karpenter\_enable\_spot\_termination) | Determines whether to enable native node termination handling | `bool` | `true` | no |
| <a name="input_karpenter_node"></a> [karpenter\_node](#input\_karpenter\_node) | Karpenter IAM role and IAM instance profile configuration values | `any` | `{}` | no |
| <a name="input_karpenter_sqs"></a> [karpenter\_sqs](#input\_karpenter\_sqs) | Karpenter SQS queue for native node termination handling configuration values | `any` | `{}` | no |
| <a name="input_kube_prometheus_stack"></a> [kube\_prometheus\_stack](#input\_kube\_prometheus\_stack) | Kube Prometheus Stack add-on configurations | `any` | `{}` | no |
| <a name="input_metrics_server"></a> [metrics\_server](#input\_metrics\_server) | Metrics Server add-on configurations | `any` | `{}` | no |
| <a name="input_observability_tag"></a> [observability\_tag](#input\_observability\_tag) | Tag to identify EKS Blueprints usage within observability tools | `string` | `"qs-1ubotj5kl"` | no |
| <a name="input_oidc_provider_arn"></a> [oidc\_provider\_arn](#input\_oidc\_provider\_arn) | The ARN of the cluster OIDC Provider | `string` | n/a | yes |
| <a name="input_secrets_store_csi_driver"></a> [secrets\_store\_csi\_driver](#input\_secrets\_store\_csi\_driver) | CSI Secrets Store Provider add-on configurations | `any` | `{}` | no |
| <a name="input_secrets_store_csi_driver_provider_aws"></a> [secrets\_store\_csi\_driver\_provider\_aws](#input\_secrets\_store\_csi\_driver\_provider\_aws) | CSI Secrets Store Provider add-on configurations | `any` | `{}` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | A map of tags to add to all resources | `map(string)` | `{}` | no |
| <a name="input_velero"></a> [velero](#input\_velero) | Velero add-on configuration values | `any` | `{}` | no |
| <a name="input_vpa"></a> [vpa](#input\_vpa) | Vertical Pod Autoscaler add-on configuration values | `any` | `{}` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_argo_events"></a> [argo\_events](#output\_argo\_events) | Map of attributes of the Helm release created |
| <a name="output_argo_rollouts"></a> [argo\_rollouts](#output\_argo\_rollouts) | Map of attributes of the Helm release created |
| <a name="output_argo_workflows"></a> [argo\_workflows](#output\_argo\_workflows) | Map of attributes of the Helm release created |
| <a name="output_argocd"></a> [argocd](#output\_argocd) | Map of attributes of the Helm release created |
| <a name="output_aws_cloudwatch_metrics"></a> [aws\_cloudwatch\_metrics](#output\_aws\_cloudwatch\_metrics) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_efs_csi_driver"></a> [aws\_efs\_csi\_driver](#output\_aws\_efs\_csi\_driver) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_for_fluentbit"></a> [aws\_for\_fluentbit](#output\_aws\_for\_fluentbit) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_fsx_csi_driver"></a> [aws\_fsx\_csi\_driver](#output\_aws\_fsx\_csi\_driver) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_gateway_api_controller"></a> [aws\_gateway\_api\_controller](#output\_aws\_gateway\_api\_controller) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_load_balancer_controller"></a> [aws\_load\_balancer\_controller](#output\_aws\_load\_balancer\_controller) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_node_termination_handler"></a> [aws\_node\_termination\_handler](#output\_aws\_node\_termination\_handler) | Map of attributes of the Helm release and IRSA created |
| <a name="output_aws_privateca_issuer"></a> [aws\_privateca\_issuer](#output\_aws\_privateca\_issuer) | Map of attributes of the Helm release and IRSA created |
| <a name="output_bottlerocket_update_operator"></a> [bottlerocket\_update\_operator](#output\_bottlerocket\_update\_operator) | Map of attributes of the Helm release and IRSA created |
| <a name="output_cert_manager"></a> [cert\_manager](#output\_cert\_manager) | Map of attributes of the Helm release and IRSA created |
| <a name="output_cluster_autoscaler"></a> [cluster\_autoscaler](#output\_cluster\_autoscaler) | Map of attributes of the Helm release and IRSA created |
| <a name="output_cluster_proportional_autoscaler"></a> [cluster\_proportional\_autoscaler](#output\_cluster\_proportional\_autoscaler) | Map of attributes of the Helm release and IRSA created |
| <a name="output_eks_addons"></a> [eks\_addons](#output\_eks\_addons) | Map of attributes for each EKS addons enabled |
| <a name="output_external_dns"></a> [external\_dns](#output\_external\_dns) | Map of attributes of the Helm release and IRSA created |
| <a name="output_external_secrets"></a> [external\_secrets](#output\_external\_secrets) | Map of attributes of the Helm release and IRSA created |
| <a name="output_fargate_fluentbit"></a> [fargate\_fluentbit](#output\_fargate\_fluentbit) | Map of attributes of the configmap and IAM policy created |
| <a name="output_gatekeeper"></a> [gatekeeper](#output\_gatekeeper) | Map of attributes of the Helm release and IRSA created |
| <a name="output_gitops_metadata"></a> [gitops\_metadata](#output\_gitops\_metadata) | GitOps Bridge metadata |
| <a name="output_helm_releases"></a> [helm\_releases](#output\_helm\_releases) | Map of attributes of the Helm release created |
| <a name="output_ingress_nginx"></a> [ingress\_nginx](#output\_ingress\_nginx) | Map of attributes of the Helm release and IRSA created |
| <a name="output_karpenter"></a> [karpenter](#output\_karpenter) | Map of attributes of the Helm release and IRSA created |
| <a name="output_kube_prometheus_stack"></a> [kube\_prometheus\_stack](#output\_kube\_prometheus\_stack) | Map of attributes of the Helm release and IRSA created |
| <a name="output_metrics_server"></a> [metrics\_server](#output\_metrics\_server) | Map of attributes of the Helm release and IRSA created |
| <a name="output_secrets_store_csi_driver"></a> [secrets\_store\_csi\_driver](#output\_secrets\_store\_csi\_driver) | Map of attributes of the Helm release and IRSA created |
| <a name="output_secrets_store_csi_driver_provider_aws"></a> [secrets\_store\_csi\_driver\_provider\_aws](#output\_secrets\_store\_csi\_driver\_provider\_aws) | Map of attributes of the Helm release and IRSA created |
| <a name="output_velero"></a> [velero](#output\_velero) | Map of attributes of the Helm release and IRSA created |
| <a name="output_vpa"></a> [vpa](#output\_vpa) | Map of attributes of the Helm release and IRSA created |
<!-- END_TF_DOCS -->
