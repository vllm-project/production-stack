## -------------------------------------------------------------------------------------------
##  Author: Kosseila HD (@CloudThrill)
##  License: MIT
##  Date: Summer 2025
##  Description: EKS add-ons (Calico CNI, Cert-Manager, Grafana, Prometheus, CSI drivers).
## -------------------------------------------------------------------------------------------
###############################################################################
# Local: decide if GPU is actually requested
###############################################################################

locals {
  gpu_selected = lower(var.inference_hardware) == "gpu"
}

###############################################################################
# Deploy Calico immediately after EKS cluster
###############################################################################

data "template_file" "calico_values" {
  template = file("${path.module}/config/calico-values.tpl")
  vars = {
    pod_cidr = var.pod_cidr
  }
}

resource "helm_release" "calico" {
  name             = "calico"
  repository       = "https://projectcalico.docs.tigera.io/charts"
  chart            = "tigera-operator"
  namespace        = "tigera-operator"
  create_namespace = true
  version          = var.calico_version
  # values         = [file(var.calico_values_file)]
  values = [data.template_file.calico_values.rendered]
   # --- new ---
   wait             = false          # don’t wait for hooks
    timeout = 900  # Wait up to 15 minutes for the release to be ready
  # ------------
  # Add a destroy-time provisioner to delete the uninstall job
  provisioner "local-exec" {
    when    = destroy
    command = <<-EOF
    KUBECONFIG=./kubeconfig kubectl -n tigera-operator delete job tigera-operator-uninstall --ignore-not-found=true || true
    KUBECONFIG=./kubeconfig kubectl patch namespace calico-system --type=merge -p '{"metadata":{"finalizers":null}}' 2>/dev/null || true
  # Delete the Installation resource that owns the calico-system namespace
    KUBECONFIG=./kubeconfig kubectl patch installation default --type=merge -p '{"metadata":{"finalizers":null}}' 2>/dev/null || true
    KUBECONFIG=./kubeconfig kubectl delete installation default --ignore-not-found=true || true
  # Also clean up the stale API service
    KUBECONFIG=./kubeconfig kubectl delete apiservice v3.projectcalico.org --ignore-not-found=true || true
  EOF
  }
  depends_on = [module.eks_addons, local_file.kubeconfig]
}

# helm -n tigera-operator uninstall calico --no-hooks
resource "time_sleep" "wait_for_addons" {
  depends_on = [module.eks]
  create_duration = "120s"  # Wait 2 minutes for addons to be ready
}
################################################################################
# Add-on modules
################################################################################
module "eks_addons" {
  source = "git::https://github.com/cloudthrill/terraform-aws-eks-modules.git//eks-blueprints-addons?ref=v1.0.0"
  # version = "~> 1.0" #ensure to update this to the latest/desired version
  cluster_name      = module.eks.cluster_name
  cluster_endpoint  = module.eks.cluster_endpoint
  oidc_provider_arn = module.eks.oidc_provider_arn
  cluster_version   = module.eks.cluster_version

  eks_addons = {
    aws-ebs-csi-driver     = { most_recent = true }
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    eks-pod-identity-agent = {}
   # vpc-cni            = { most_recent = false, preserve = false }  # <--
  #  vpc-cni = {
  #   most_recent = true
  #   configuration_values = jsonencode({
  #     env = {
  #       ENABLE_PREFIX_DELEGATION = "true"
  #       WARM_PREFIX_TARGET = "1"
  #     }
  #   })
 #

  }
# In versions 2.5+ of aws-load-balancer-controller.addons that have services (i.e cert manager) may timeout waiting for the LB webhook to be available.
# due to no endpoints ready. Terraform therefore bombs at the first apply.
# fix this by disabling the mutator webhook
  aws_load_balancer_controller = {
     set = [
    {
      name  = "enableServiceMutatorWebhook"
      value = "false"
    }
  ]
  }
  enable_aws_load_balancer_controller = var.enable_lb_ctl
  enable_external_dns                 = var.enable_external_dns
  enable_metrics_server               = var.enable_metrics_server
  enable_cert_manager                 = var.enable_cert_manager
  enable_karpenter                    = var.enable_karpenter
  enable_kube_prometheus_stack        = var.enable_kube_prometheus_stack
  enable_aws_efs_csi_driver           = var.enable_efs_csi_driver
  enable_external_secrets             = var.enable_external_secrets
  enable_aws_cloudwatch_metrics       = var.enable_cloudwatch
  enable_vpa                          = var.enable_vpa
  # enable_cluster_proportional_autoscaler = var.enable_autoscaler
  # enable_aws_ebs_csi_driver              = var.enable_ebs_csi_driver
  # enable_aws_privateca_issuer           = var.enable_privateca_issuer
  # external_secrets_secrets_manager_arns = var.external_secrets_secrets_manager_arns
  # external_secrets_ssm_parameter_arns = var.external_secrets_ssm_parameter_arns
  # enable_aws_fsx_csi_driver            = var.enable_fsx_csi_driver
  # external_secrets_kms_key_arns        = var.external_secrets_kms_key_arns
  # ingress_nginx                        = var.enable_ingress_nginx
  # secrets_store_csi_driver = var.enable_secrets_store_csi_driver
  # secrets_store_csi_driver_provider_aws
  # Pass in any number of Helm charts to be created for those that are not natively supported
  # helm_releases = {
  #   calico = {
  #     chart            = "tigera-operator"
  #     repository       = "https://projectcalico.docs.tigera.io/charts"
  #     namespace        = "tigera-operator"
  #     chart_version    = var.calico_version
  #     values           = [file(var.calico_values_file)]
  #     create_namespace = true
  #   }
  # }

  tags = var.tags
  depends_on = [module.eks, ]  # Ensure EKS cluster is ready before deploying add-ons time_sleep.wait_for_addons,
}

resource "kubernetes_storage_class" "gp3" {
  depends_on = [module.eks_addons]

  metadata {
    name = "gp3"
    annotations = {
      "storageclass.kubernetes.io/is-default-class" = "true"
    }
  }

  storage_provisioner    = "ebs.csi.aws.com"
  reclaim_policy        = "Delete"
  volume_binding_mode   = "WaitForFirstConsumer"
  allow_volume_expansion = true

  parameters = {
    type      = "gp3"
    encrypted = "true"
  }
}

# get grafana admin password
# kubectl get secret -n kube-prometheus-stack kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 --decode
################################################################################
# 🛠️  GPU OPERATOR ADD-ON
################################################################################


locals {
  # Flags for each scenario
  enable_nvidia_operator = contains(["operator_custom", "operator_no_driver"], var.nvidia_setup)
  operator_use_values    = var.nvidia_setup == "operator_custom"
  enable_nvidia_plugin = contains(["plugin"], var.nvidia_setup)

  # Map-style overrides only for the no-driver path
  operator_inline_set = var.nvidia_setup == "operator_no_driver" ? [
    { name = "driver.enabled", value = "false" },
    { name = "toolkit.enabled", value = "false" }
  ] : []
}


module "data_addons" {
  source = "git::https://github.com/cloudthrill/terraform-aws-eks-modules.git//eks-data-addons?ref=v1.0.0"

  # --- required oidc provider arn ---
  oidc_provider_arn = module.eks.oidc_provider_arn

  # --- NVIDIA GPU Setup Selector ---
  # GPU Operator only when hardware inference = gpu *and* user opted for operator
  enable_nvidia_gpu_operator = local.gpu_selected && local.enable_nvidia_operator

  nvidia_gpu_operator_helm_config = local.enable_nvidia_operator ? (
    local.operator_use_values ? {
      version   = "v25.3.1"
      namespace = "gpu-operator"
      values    = [file(var.gpu_operator_file)]
      } : {
      version   = "v25.3.1"
      namespace = "gpu-operator"
      set       = local.operator_inline_set
    }
  ) : null
  depends_on = [module.eks_addons]
  # Device‑plugin only scenario handled via custom_addons in the parent module
enable_nvidia_device_plugin = local.gpu_selected && local.enable_nvidia_plugin
nvidia_device_plugin_helm_config = local.enable_nvidia_plugin ? {
  tolerations = [{
    key      = "nvidia.com/gpu"
    operator = "Exists"
    effect   = "NoSchedule"
  }]
}: null
}

# 💡Destroy tips
# If you face terraform destroy issues because of * jobs.batch "tigera-operator-uninstall" already exists
# use the following commands to delete the jobs manually first:
# 1.  kubectl -n tigera-operator delete job tigera-operator-uninstall --ignore-not-found=true
# 2.  kubectl -n tigera-operator delete job tigera-operator-delete-crds --ignore-not-found=true
# 3.  kubectl delete ns tigera-operator --ignore-not-found=true
# Other discovery commands:
# 1. kubectl get all -n tigera-operator
# 2. kubectl get installation -o yaml | yq '.items[].spec.cni.type'
# 3. kubectl get ds -n calico-system -w
# 4. kubectl get tigerastatus
