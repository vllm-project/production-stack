output "airflow" {
  value       = try(helm_release.airflow[0].metadata, null)
  description = "Airflow Helm Chart metadata"
}

output "aws_efa_k8s_device_plugin" {
  value       = try(helm_release.aws_efa_k8s_device_plugin, null)
  description = "AWS EFA K8s Plugin Helm Chart metadata"
}

output "aws_neuron_device_plugin" {
  value       = try(helm_release.aws_neuron_device_plugin, null)
  description = "AWS Neuron Device Plugin Helm Chart metadata"
}

 

output "kubecost" {
  value       = try(helm_release.kubecost[0].metadata, null)
  description = "Kubecost Helm Chart metadata"
}

output "nvidia_gpu_operator" {
  value       = try(helm_release.nvidia_gpu_operator[0].metadata, null)
  description = "Nvidia GPU Operator Helm Chart metadata"
}


  
output "kuberay_operator" {
  value       = try(helm_release.kuberay_operator[0].metadata, null)
  description = "Kuberay Operator Helm Chart metadata"
}
 
 