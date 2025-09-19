variable "oidc_provider_arn" {
  description = "The ARN of the cluster OIDC Provider"
  type        = string
}

#---------------------------------------------------
# SPARK K8S OPERATOR
#---------------------------------------------------
variable "enable_spark_operator" {
  description = "Enable Spark on K8s Operator add-on"
  type        = bool
  default     = false
}

variable "spark_operator_helm_config" {
  description = "Helm configuration for Spark K8s Operator"
  type        = any
  default     = {}
}

#---------------------------------------------------
# APACHE YUNIKORN
#---------------------------------------------------
variable "enable_yunikorn" {
  description = "Enable Apache YuniKorn K8s scheduler add-on"
  type        = bool
  default     = false
}

variable "yunikorn_helm_config" {
  description = "Helm configuration for Apache YuniKorn"
  type        = any
  default     = {}
}

#---------------------------------------------------
# SPARK HISTORY SERVER
#---------------------------------------------------
variable "enable_spark_history_server" {
  description = "Enable Spark History Server add-on"
  type        = bool
  default     = false
}

variable "spark_history_server_helm_config" {
  description = "Helm configuration for Spark History Server"
  type        = any
  default     = {}
}

#---------------------------------------------------
# KUBECOST
#---------------------------------------------------
variable "enable_kubecost" {
  description = "Enable Kubecost add-on"
  type        = bool
  default     = false
}

variable "kubecost_helm_config" {
  description = "Kubecost Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# FLINK OPERATOR
#---------------------------------------------------
variable "enable_flink_operator" {
  description = "Enable Flink Operator add-on"
  type        = bool
  default     = false
}

variable "flink_operator_helm_config" {
  description = "Flink Operator Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# NVIDIA GPU OPERATOR
#---------------------------------------------------
variable "enable_nvidia_gpu_operator" {
  description = "Enable NVIDIA GPU Operator add-on"
  type        = bool
  default     = false
}

variable "nvidia_gpu_operator_helm_config" {
  description = "Helm configuration for NVIDIA GPU Operator"
  type        = any
  default     = {}
}

#---------------------------------------------------
# EMR Runtime Spark Operator
#---------------------------------------------------
variable "enable_emr_spark_operator" {
  description = "Enable the Spark Operator to submit jobs with EMR Runtime"
  type        = bool
  default     = false
}

variable "emr_spark_operator_helm_config" {
  description = "Helm configuration for Spark Operator with EMR Runtime"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Srimzi Kafka Operator
#---------------------------------------------------
variable "enable_strimzi_kafka_operator" {
  description = "Enable the Strimzi Kafka Operator"
  type        = bool
  default     = false
}

variable "strimzi_kafka_operator_helm_config" {
  description = "Helm configuration for Strimzi Kafka Operator"
  type        = any
  default     = {}
}

#---------------------------------------------------
# JUPYTERHUB
#---------------------------------------------------
variable "enable_jupyterhub" {
  description = "Enable Jupyterhub Add-On"
  type        = bool
  default     = false
}

variable "jupyterhub_helm_config" {
  description = "Helm configuration for JupyterHub"
  type        = any
  default     = {}
}

#---------------------------------------------------
# AIRFLOW
#---------------------------------------------------
variable "enable_airflow" {
  description = "Enable Airflow add-on"
  type        = bool
  default     = false
}

variable "airflow_helm_config" {
  description = "Airflow Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# AWS Neuron Device Plugin (Using Local Helm Chart)
#---------------------------------------------------
variable "enable_aws_neuron_device_plugin" {
  description = "Enable AWS Neuron Device Plugin add-on"
  type        = bool
  default     = false
}

variable "aws_neuron_device_plugin_helm_config" {
  description = "AWS Neuron Device Plugin Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# AWS EFA K8s Device Plugin (Using Local Helm Chart)
#---------------------------------------------------
variable "enable_aws_efa_k8s_device_plugin" {
  description = "Enable EFA K8s Plugin add-on"
  type        = bool
  default     = false
}

variable "aws_efa_k8s_device_plugin_helm_config" {
  description = "EFA K8s Plugin add-on Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# KUBERAY OPERATOR
#---------------------------------------------------
variable "enable_kuberay_operator" {
  description = "Enable Kuberay Operator add-on"
  type        = bool
  default     = false
}

variable "kuberay_operator_helm_config" {
  description = "Helm configuration for Kuberay Operator"
  type        = any
  default     = {}
}

#---------------------------------------------------
# CloudNative PG OPERATOR
#---------------------------------------------------
variable "enable_cnpg_operator" {
  description = "Enable CloudNative PG Operator add-on"
  type        = bool
  default     = false
}

variable "cnpg_operator_helm_config" {
  description = "CloudNative PG Operator Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Volcano Batch Scheduler
#---------------------------------------------------
variable "enable_volcano" {
  description = "Enable volcano scheduler add-on"
  type        = bool
  default     = false
}

variable "volcano_helm_config" {
  description = "Volcano scheduler add-on configurations"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Dask Operator
#---------------------------------------------------

variable "enable_dask_operator" {
  description = "Enable Dask Operator add-on"
  type        = bool
  default     = false
}

variable "dask_operator_helm_config" {
  description = "Dask Operator add-on configurations"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Dask Hub Operator
#---------------------------------------------------

variable "enable_daskhub" {
  description = "Enable DaskHub"
  type        = bool
  default     = false
}

variable "daskhub_helm_config" {
  description = "DaskHub add-on configurations"
  type        = any
  default     = {}
}

#---------------------------------------------------
# MLflow Tracking (Using Local Helm Chart)
#---------------------------------------------------
variable "enable_mlflow_tracking" {
  description = "Enable MLflow Tracking add-on"
  type        = bool
  default     = false
}

variable "mlflow_tracking_helm_config" {
  description = "MLflow Tracking add-on Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# EMR Runtime Flink Operator
#---------------------------------------------------
variable "enable_emr_flink_operator" {
  description = "Enable the Flink Operator to run Flink application with EMR Runtime"
  type        = bool
  default     = false
}

variable "emr_flink_operator_helm_config" {
  description = "Helm configuration for Flink Operator with EMR Runtime"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Apache Pinot
#---------------------------------------------------
variable "enable_pinot" {
  description = "Enable Apache Pinot Add-On"
  type        = bool
  default     = false
}

variable "pinot_helm_config" {
  description = "Apache Pinot Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Karpenter Resources
#---------------------------------------------------
variable "enable_karpenter_resources" {
  description = "Enable Karpenter Resources (NodePool and EC2NodeClass)"
  type        = bool
  default     = false
}

variable "karpenter_resources_helm_config" {
  description = "Karpenter Resources Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# NVIDIA Device Plugin
#---------------------------------------------------
variable "enable_nvidia_device_plugin" {
  description = "Enable NVIDIA Device Plugin add-on"
  type        = bool
  default     = false
}

variable "nvidia_device_plugin_helm_config" {
  description = "NVIDIA Device Plugin Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Trino
#---------------------------------------------------
variable "enable_trino" {
  description = "Enable Trino add-on"
  type        = bool
  default     = false
}

variable "trino_helm_config" {
  description = "Trino Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Apache Superset
#---------------------------------------------------
variable "enable_superset" {
  description = "Enable Apache Supeset add-on"
  type        = bool
  default     = false
}

variable "superset_helm_config" {
  description = "Apache Supeset Helm Chart config"
  type        = any
  default     = {}
}

#---------------------------------------------------
# Qdrant
#---------------------------------------------------
variable "enable_qdrant" {
  description = "Enable Qdrant Vector Database add-on"
  type        = bool
  default     = false
}

variable "enable_nvidia_triton_server" {
  description = "Enable NVIDIA Triton Server add-on"
  type        = bool
  default     = false
}

variable "qdrant_helm_config" {
  description = "Helm configuration for Qdrant"
  type        = any
  default     = {}
}

variable "nvidia_triton_server_helm_config" {
  description = "Helm configuration for NVIDIA Triton Server"
  type        = any
  default     = {}
}
