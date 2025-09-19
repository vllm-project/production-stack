Terraform Module: :rocket: Data & AI/ML Kubernetes Add-ons :gear:

This Terraform module contains commonly used **Data & AI/ML** related [Kubernetes](https://kubernetes.io/) add-ons that are typically included in [Data on EKS](https://github.com/awslabs/data-on-eks) blueprints.
The purpose of this module is to provide users with the flexibility to select and customize the add-ons they require while leveraging the Data on EKS blueprints.

:warning: **Important Note**

Users can consume this Terraform module in their projects to deploy any of the available addons. We will continue to maintain and update the existing Data/ML add-ons. However, we kindly request that you refrain from submitting Pull Requests (PRs) to add new addons at the moment, unless there is a supported blueprint available in the [Data on EKS](https://github.com/awslabs/data-on-eks) repository. The Apache and CNCF communities offer numerous open-source Data and ML add-ons, and while we appreciate their value, supporting all of them poses challenges.

Your understanding and cooperation are highly appreciated. :pray:

## Usage

Create Addon with the following example using Terraform registry. Checkout the complete example under `test` folder.

```hcl
module "eks_data_addons" {
  source = "aws-ia/eks-data-addons/aws"
  version = "~> 1.0" # ensure to update this to the latest/desired version

  oidc_provider_arn = module.eks.oidc_provider_arn

  # Example to deploy AWS Neuron Device Plugin for Trainium and Inferentia instances
  enable_aws_efa_k8s_device_plugin = true

  # Example to deploy EFA K8s Device Plugin for GPU/Neuron instances
  enable_aws_efa_k8s_device_plugin = true

  # Example to deploy NVIDIA GPU Operator
  enable_nvidia_gpu_operator = true

  # Example to deploy Spark Operator Helm Chart
  enable_spark_opertor = true

  # Example to deploy Flink Operator Helm Chart
  enable_flink_operator = true

  # Example to deploy Apache YuniKorn Helm Chart
  enable_yunikorn = true

  # Example that uses ECR authentication for a particular registry ID
  enable_emr_spark_operator = var.enable_emr_spark_operator
  emr_spark_operator_helm_config = {
    repository_username = data.aws_ecr_authorization_token.token.user_name
    repository_password = data.aws_ecr_authorization_token.token.password
  }

  # Example to deploy Helm chart that uses IAM Role for ServiceAccounts. You can disable `create_irsa` and bring your own IAM role.
  enable_spark_history_server = var.enable_emr_spark_operator
  spark_history_server_helm_config = {
    create_irsa = true
    values = [
      templatefile("${path.module}/test/helm-values/spark-history-server-values.yaml", {
        s3_bucket_name   = module.s3_bucket.s3_bucket_id
        s3_bucket_prefix = aws_s3_object.this.key
      })
    ]
  }
}
```

## Support & Feedback

> [!IMPORTANT]
> EKS Blueprints for Terraform is maintained by AWS Solution Architects. It is not part of an AWS
> service and support is provided as a best-effort by the EKS Blueprints community. To provide feedback,
> please use the [issues templates](https://github.com/aws-ia/terraform-aws-eks-data-addons/issues)
> provided. If you are interested in contributing to EKS Blueprints, see the
> [Contribution guide](https://github.com/aws-ia/terraform-aws-eks-data-addons/blob/main/.github/CONTRIBUTING.md).

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >= 1.0.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 3.72 |
| <a name="requirement_helm"></a> [helm](#requirement\_helm) | >= 2.4.1 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | >= 3.72 |
| <a name="provider_helm"></a> [helm](#provider\_helm) | >= 2.4.1 |

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_spark_history_server_irsa"></a> [spark\_history\_server\_irsa](#module\_spark\_history\_server\_irsa) | ./irsa | n/a |

## Resources

| Name | Type |
|------|------|
| [helm_release.airflow](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.aws_efa_k8s_device_plugin](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.aws_neuron_device_plugin](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.cnpg_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.dask_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.daskhub](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.emr_flink_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.emr_spark_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.flink_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.jupyterhub](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.karpenter_resources](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.kubecost](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.kuberay_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.mlflow_tracking](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.nvidia_device_plugin](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.nvidia_gpu_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.nvidia_triton_server](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.pinot](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.qdrant](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.spark_history_server](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.spark_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.strimzi_kafka_operator](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.superset](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.trino](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.volcano](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.yunikorn](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_airflow_helm_config"></a> [airflow\_helm\_config](#input\_airflow\_helm\_config) | Airflow Helm Chart config | `any` | `{}` | no |
| <a name="input_aws_efa_k8s_device_plugin_helm_config"></a> [aws\_efa\_k8s\_device\_plugin\_helm\_config](#input\_aws\_efa\_k8s\_device\_plugin\_helm\_config) | EFA K8s Plugin add-on Helm Chart config | `any` | `{}` | no |
| <a name="input_aws_neuron_device_plugin_helm_config"></a> [aws\_neuron\_device\_plugin\_helm\_config](#input\_aws\_neuron\_device\_plugin\_helm\_config) | AWS Neuron Device Plugin Helm Chart config | `any` | `{}` | no |
| <a name="input_cnpg_operator_helm_config"></a> [cnpg\_operator\_helm\_config](#input\_cnpg\_operator\_helm\_config) | CloudNative PG Operator Helm Chart config | `any` | `{}` | no |
| <a name="input_dask_operator_helm_config"></a> [dask\_operator\_helm\_config](#input\_dask\_operator\_helm\_config) | Dask Operator add-on configurations | `any` | `{}` | no |
| <a name="input_daskhub_helm_config"></a> [daskhub\_helm\_config](#input\_daskhub\_helm\_config) | DaskHub add-on configurations | `any` | `{}` | no |
| <a name="input_emr_flink_operator_helm_config"></a> [emr\_flink\_operator\_helm\_config](#input\_emr\_flink\_operator\_helm\_config) | Helm configuration for Flink Operator with EMR Runtime | `any` | `{}` | no |
| <a name="input_emr_spark_operator_helm_config"></a> [emr\_spark\_operator\_helm\_config](#input\_emr\_spark\_operator\_helm\_config) | Helm configuration for Spark Operator with EMR Runtime | `any` | `{}` | no |
| <a name="input_enable_airflow"></a> [enable\_airflow](#input\_enable\_airflow) | Enable Airflow add-on | `bool` | `false` | no |
| <a name="input_enable_aws_efa_k8s_device_plugin"></a> [enable\_aws\_efa\_k8s\_device\_plugin](#input\_enable\_aws\_efa\_k8s\_device\_plugin) | Enable EFA K8s Plugin add-on | `bool` | `false` | no |
| <a name="input_enable_aws_neuron_device_plugin"></a> [enable\_aws\_neuron\_device\_plugin](#input\_enable\_aws\_neuron\_device\_plugin) | Enable AWS Neuron Device Plugin add-on | `bool` | `false` | no |
| <a name="input_enable_cnpg_operator"></a> [enable\_cnpg\_operator](#input\_enable\_cnpg\_operator) | Enable CloudNative PG Operator add-on | `bool` | `false` | no |
| <a name="input_enable_dask_operator"></a> [enable\_dask\_operator](#input\_enable\_dask\_operator) | Enable Dask Operator add-on | `bool` | `false` | no |
| <a name="input_enable_daskhub"></a> [enable\_daskhub](#input\_enable\_daskhub) | Enable DaskHub | `bool` | `false` | no |
| <a name="input_enable_emr_flink_operator"></a> [enable\_emr\_flink\_operator](#input\_enable\_emr\_flink\_operator) | Enable the Flink Operator to run Flink application with EMR Runtime | `bool` | `false` | no |
| <a name="input_enable_emr_spark_operator"></a> [enable\_emr\_spark\_operator](#input\_enable\_emr\_spark\_operator) | Enable the Spark Operator to submit jobs with EMR Runtime | `bool` | `false` | no |
| <a name="input_enable_flink_operator"></a> [enable\_flink\_operator](#input\_enable\_flink\_operator) | Enable Flink Operator add-on | `bool` | `false` | no |
| <a name="input_enable_jupyterhub"></a> [enable\_jupyterhub](#input\_enable\_jupyterhub) | Enable Jupyterhub Add-On | `bool` | `false` | no |
| <a name="input_enable_karpenter_resources"></a> [enable\_karpenter\_resources](#input\_enable\_karpenter\_resources) | Enable Karpenter Resources (NodePool and EC2NodeClass) | `bool` | `false` | no |
| <a name="input_enable_kubecost"></a> [enable\_kubecost](#input\_enable\_kubecost) | Enable Kubecost add-on | `bool` | `false` | no |
| <a name="input_enable_kuberay_operator"></a> [enable\_kuberay\_operator](#input\_enable\_kuberay\_operator) | Enable Kuberay Operator add-on | `bool` | `false` | no |
| <a name="input_enable_mlflow_tracking"></a> [enable\_mlflow\_tracking](#input\_enable\_mlflow\_tracking) | Enable MLflow Tracking add-on | `bool` | `false` | no |
| <a name="input_enable_nvidia_device_plugin"></a> [enable\_nvidia\_device\_plugin](#input\_enable\_nvidia\_device\_plugin) | Enable NVIDIA Device Plugin add-on | `bool` | `false` | no |
| <a name="input_enable_nvidia_gpu_operator"></a> [enable\_nvidia\_gpu\_operator](#input\_enable\_nvidia\_gpu\_operator) | Enable NVIDIA GPU Operator add-on | `bool` | `false` | no |
| <a name="input_enable_nvidia_triton_server"></a> [enable\_nvidia\_triton\_server](#input\_enable\_nvidia\_triton\_server) | Enable NVIDIA Triton Server add-on | `bool` | `false` | no |
| <a name="input_enable_pinot"></a> [enable\_pinot](#input\_enable\_pinot) | Enable Apache Pinot Add-On | `bool` | `false` | no |
| <a name="input_enable_qdrant"></a> [enable\_qdrant](#input\_enable\_qdrant) | Enable Qdrant Vector Database add-on | `bool` | `false` | no |
| <a name="input_enable_spark_history_server"></a> [enable\_spark\_history\_server](#input\_enable\_spark\_history\_server) | Enable Spark History Server add-on | `bool` | `false` | no |
| <a name="input_enable_spark_operator"></a> [enable\_spark\_operator](#input\_enable\_spark\_operator) | Enable Spark on K8s Operator add-on | `bool` | `false` | no |
| <a name="input_enable_strimzi_kafka_operator"></a> [enable\_strimzi\_kafka\_operator](#input\_enable\_strimzi\_kafka\_operator) | Enable the Strimzi Kafka Operator | `bool` | `false` | no |
| <a name="input_enable_superset"></a> [enable\_superset](#input\_enable\_superset) | Enable Apache Supeset add-on | `bool` | `false` | no |
| <a name="input_enable_trino"></a> [enable\_trino](#input\_enable\_trino) | Enable Trino add-on | `bool` | `false` | no |
| <a name="input_enable_volcano"></a> [enable\_volcano](#input\_enable\_volcano) | Enable volcano scheduler add-on | `bool` | `false` | no |
| <a name="input_enable_yunikorn"></a> [enable\_yunikorn](#input\_enable\_yunikorn) | Enable Apache YuniKorn K8s scheduler add-on | `bool` | `false` | no |
| <a name="input_flink_operator_helm_config"></a> [flink\_operator\_helm\_config](#input\_flink\_operator\_helm\_config) | Flink Operator Helm Chart config | `any` | `{}` | no |
| <a name="input_jupyterhub_helm_config"></a> [jupyterhub\_helm\_config](#input\_jupyterhub\_helm\_config) | Helm configuration for JupyterHub | `any` | `{}` | no |
| <a name="input_karpenter_resources_helm_config"></a> [karpenter\_resources\_helm\_config](#input\_karpenter\_resources\_helm\_config) | Karpenter Resources Helm Chart config | `any` | `{}` | no |
| <a name="input_kubecost_helm_config"></a> [kubecost\_helm\_config](#input\_kubecost\_helm\_config) | Kubecost Helm Chart config | `any` | `{}` | no |
| <a name="input_kuberay_operator_helm_config"></a> [kuberay\_operator\_helm\_config](#input\_kuberay\_operator\_helm\_config) | Helm configuration for Kuberay Operator | `any` | `{}` | no |
| <a name="input_mlflow_tracking_helm_config"></a> [mlflow\_tracking\_helm\_config](#input\_mlflow\_tracking\_helm\_config) | MLflow Tracking add-on Helm Chart config | `any` | `{}` | no |
| <a name="input_nvidia_device_plugin_helm_config"></a> [nvidia\_device\_plugin\_helm\_config](#input\_nvidia\_device\_plugin\_helm\_config) | NVIDIA Device Plugin Helm Chart config | `any` | `{}` | no |
| <a name="input_nvidia_gpu_operator_helm_config"></a> [nvidia\_gpu\_operator\_helm\_config](#input\_nvidia\_gpu\_operator\_helm\_config) | Helm configuration for NVIDIA GPU Operator | `any` | `{}` | no |
| <a name="input_nvidia_triton_server_helm_config"></a> [nvidia\_triton\_server\_helm\_config](#input\_nvidia\_triton\_server\_helm\_config) | Helm configuration for NVIDIA Triton Server | `any` | `{}` | no |
| <a name="input_oidc_provider_arn"></a> [oidc\_provider\_arn](#input\_oidc\_provider\_arn) | The ARN of the cluster OIDC Provider | `string` | n/a | yes |
| <a name="input_pinot_helm_config"></a> [pinot\_helm\_config](#input\_pinot\_helm\_config) | Apache Pinot Helm Chart config | `any` | `{}` | no |
| <a name="input_qdrant_helm_config"></a> [qdrant\_helm\_config](#input\_qdrant\_helm\_config) | Helm configuration for Qdrant | `any` | `{}` | no |
| <a name="input_spark_history_server_helm_config"></a> [spark\_history\_server\_helm\_config](#input\_spark\_history\_server\_helm\_config) | Helm configuration for Spark History Server | `any` | `{}` | no |
| <a name="input_spark_operator_helm_config"></a> [spark\_operator\_helm\_config](#input\_spark\_operator\_helm\_config) | Helm configuration for Spark K8s Operator | `any` | `{}` | no |
| <a name="input_strimzi_kafka_operator_helm_config"></a> [strimzi\_kafka\_operator\_helm\_config](#input\_strimzi\_kafka\_operator\_helm\_config) | Helm configuration for Strimzi Kafka Operator | `any` | `{}` | no |
| <a name="input_superset_helm_config"></a> [superset\_helm\_config](#input\_superset\_helm\_config) | Apache Supeset Helm Chart config | `any` | `{}` | no |
| <a name="input_trino_helm_config"></a> [trino\_helm\_config](#input\_trino\_helm\_config) | Trino Helm Chart config | `any` | `{}` | no |
| <a name="input_volcano_helm_config"></a> [volcano\_helm\_config](#input\_volcano\_helm\_config) | Volcano scheduler add-on configurations | `any` | `{}` | no |
| <a name="input_yunikorn_helm_config"></a> [yunikorn\_helm\_config](#input\_yunikorn\_helm\_config) | Helm configuration for Apache YuniKorn | `any` | `{}` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_airflow"></a> [airflow](#output\_airflow) | Airflow Helm Chart metadata |
| <a name="output_aws_efa_k8s_device_plugin"></a> [aws\_efa\_k8s\_device\_plugin](#output\_aws\_efa\_k8s\_device\_plugin) | AWS EFA K8s Plugin Helm Chart metadata |
| <a name="output_aws_neuron_device_plugin"></a> [aws\_neuron\_device\_plugin](#output\_aws\_neuron\_device\_plugin) | AWS Neuron Device Plugin Helm Chart metadata |
| <a name="output_dask_hub"></a> [dask\_hub](#output\_dask\_hub) | Dask Hub Helm Chart metadata |
| <a name="output_dask_operator"></a> [dask\_operator](#output\_dask\_operator) | Dask Operator Helm Chart metadata |
| <a name="output_emr_spark_operator"></a> [emr\_spark\_operator](#output\_emr\_spark\_operator) | EMR Spark Operator Helm Chart metadata |
| <a name="output_flink_operator"></a> [flink\_operator](#output\_flink\_operator) | Flink Operator Helm Chart metadata |
| <a name="output_jupyterhub"></a> [jupyterhub](#output\_jupyterhub) | Jupyterhub Helm Chart metadata |
| <a name="output_kubecost"></a> [kubecost](#output\_kubecost) | Kubecost Helm Chart metadata |
| <a name="output_kuberay_operator"></a> [kuberay\_operator](#output\_kuberay\_operator) | Kuberay Operator Helm Chart metadata |
| <a name="output_nvidia_gpu_operator"></a> [nvidia\_gpu\_operator](#output\_nvidia\_gpu\_operator) | Nvidia GPU Operator Helm Chart metadata |
| <a name="output_pinot"></a> [pinot](#output\_pinot) | Apache Pinot Helm Chart metadata |
| <a name="output_spark_history_server"></a> [spark\_history\_server](#output\_spark\_history\_server) | Spark History Server Helm Chart metadata |
| <a name="output_spark_operator"></a> [spark\_operator](#output\_spark\_operator) | Spark Operator Helm Chart metadata |
| <a name="output_strimzi_kafka_operator"></a> [strimzi\_kafka\_operator](#output\_strimzi\_kafka\_operator) | Strimzi Kafka Operator Helm Chart metadata |
| <a name="output_volcano"></a> [volcano](#output\_volcano) | Volcano Batch Scheduler Helm Chart metadata |
| <a name="output_yunikorn"></a> [yunikorn](#output\_yunikorn) | Yunikorn Helm Chart metadata |
<!-- END_TF_DOCS -->
