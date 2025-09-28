# 🧑🏼‍🚀 vLLM Production Stack on Amazon EKS with terraform

✍🏼 This terraform stack delivers a **production-ready vLLM serving environment** On Amazon EKS supporting both CPU/GPU inference with operational best practices embedded in [AWS Integration and Automation](https://github.com/aws-ia) (security, scalability, observability).

|Project Item |Description|
|---|---|
| **Author** | [@cloudthrill](https://cloudthrill.ca) |
| **Stack**  | Terraform ◦ AWS ◦ EKS ◦ Calico ◦ Helm ◦ vLLM |
| **Module** | Highly customizable, lightweight EKS blueprint for deploying vLLM on enterprise-grade cluster|
| **CNI**    | AWS VPC with full-overlay **Calico** networ|
| **Inference hardware** | Either CPU or GPU through a switch fla|

<!-- markdownlint-disable MD051 MD036 MD056 -->
## 📋 Table of Contents

1. [Project structure](#-project-structure)
2. [Prerequisites](#-prerequisites)
3. [What Terraform Deploys](#%EF%B8%8F-what-terraform-deploys)
4. [Hardware Options](#-hardware-options)
5. [Configuration knobs](#%EF%B8%8Fconfiguration-knobs)
6. [Quick start](#-quick-start)
7. [Quick Test](#-quick-test)
8. [Observability](#-observability)
9. [Troubleshooting](#-troubleshooting)
10. [Cleanup Notes](#-cleanup-notes)
11. [Additional Resources](#-additional-resources)

---

## 📂 Project Structure

```bash
./
├── main.tf
├── network.tf
├── storage.tf
├── provider.tf
├── variables.tf
├── output.tf
├── cluster-tools.tf
├── datasources.tf
├── iam_role.tf
├── vllm-production-stack.tf
├── env-vars.template
├── terraform.tfvars.template
├── modules/
│   ├── aws-networking/
│   │   └── aws-vpc/
│   ├── aws-eks/
│   ├── eks-blueprints-addons/
|   ├── eks-data-addons|
│   └── llm-stack
|       ├── helm|
|           ├── cpu|
|           └── gpu|
├── config/
│   ├── calico-values.tpl
│   └── kubeconfig.tpl
└── README.md                          # ← you are here

```

---

## ✅ Prerequisites

| Tool | Version tested | Notes |
|------|---------------|-------|
| **Terraform** | ≥ 1.5.7 | tested on 1.5.7 |
| **AWS CLI v2** | ≥ 2.16 | profile / SSO auth |
| **kubectl** | ≥ 1.30 | ±1 of control-plane |
| **helm** | ≥ 3.14 | used by `helm_release` |
| **jq** | optional | JSON helper |
| **openssl / base64** | optional | secret helpers |

<details>
 <summary><b>Follow steps to Install tools (Ubuntu/Debian) below 👇🏼</b></summary>

 ```bash
# Install tools
sudo apt update && sudo apt install -y jq curl unzip gpg
wget -qO- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install -y terraform
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && unzip -q awscliv2.zip && sudo ./aws/install && rm -rf aws awscliv2.zip
curl -sLO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && sudo install kubectl /usr/local/bin/ && rm kubectl
curl -s https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg >/dev/null && echo "deb [signed-by=/usr/share/keyrings/helm.gpg] https://baltocdn.com/helm/stable/debian/ all main" | sudo tee /etc/apt/sources.list.d/helm.list && sudo apt update && sudo apt install -y helm
```

</details>

**Configure AWS**

```bash
aws configure --profile myprofile
export AWS_PROFILE=myprofile        # ← If null Terraform exec auth will use the default profile
```

---

## 🏗️ What Terraform Deploys

<div align="center">

| Layer | Component | CPU Mode | GPU Mode |
|------|-----------|----------|----------|
| **Infrastructure** | VPC + EKS + Calico CNI | ✅ Always deployed | ✅ Always deployed |
| **Add-ons** | EBS, ALB, Prometheus stack | ✅ Always deployed | ✅ Always deployed |
| **vLLM Stack** | Secrets + Helm chart | ✅ Deploy on CPU nodes | ✅ + GPU nodes + NVIDIA operator |
| **Networking** | Load balancer + Ingress | ✅ ALB configuration | ✅ ALB configuration |

</div>
<div align="center">
<img width="266" height="496" alt="image" src="https://github.com/user-attachments/assets/47123e7d-5d30-448d-9266-ba7082403d3b" />
<p><em>Figure-1 dependency chain of the eks addon layer with vllm on cpu</em></p>
</div>

### 1.📶 Networking

* Custom `/16` VPC with 3 public + 3 private subnets
* Single NAT GW (cost-optimized)
* **Calico overlay CNI** with VXLAN encapsulation (110+ pods/node vs 17 with VPC CNI)
* AWS Load Balancer Controller for ingress exposure
* Kubernetes-friendly subnet tagging and IAM roles

### 2. ☸️ EKS Cluster

* Control plane v1.30 with two managed node-group Types

| Pool | Instance | Purpose |
|------|----------|---------|
| `cpu_pool` (default) | **t3a.large** (2 vCPU / 8 GiB) | control & CPU inference |
| `gpu_pool` *(optional)* | **g5.xlarge** (1 × A10 GPU) | heavy inference or training |

### 3. 📦 Add-ons (“Blueprints”)

Core EKS add-ons via [terraform-aws-eks-**blueprints-addons**](https://github.com/aws-ia/terraform-aws-eks-blueprints-addons) along with gpu operator via [terraform-aws-eks-data-addons](https://github.com/aws-ia/terraform-aws-eks-data-addons).

| Category      | Add-on |
|---------------|--------|
| **CNI**       | **Calico overlay** (primary) (VPC-CNI removed) |
| **Storage**   | **EBS CSI** (block)<br/>**EFS CSI** (shared) |
| **Ingress/LB**| **AWS Load Balancer Controller** (ALB/NLB) |
| **EKS add-ons**      | CoreDNS, kube-proxy, Metrics Server |
| **Observability** | kube-prometheus-stack, CloudWatch metrics |
| **Security**  | cert-manager, External-DNS / External-Secrets |
| **Optional**  | NVIDIA Optional GPU operator toggle |

### 4. 🧠 vLLM Production Stack (CPU/GPU)

* **Model serving**: (Default) Single TinyLlama-1.1B model replica
* **Load balancing**: Round-robin router service
* **Hugging Face token**: stored as Kubernetes Secret
* **LLM Storage**: Init container Persistent model caching under `/data/models/`
* **Default Helm charts**: [cpu-tinyllama-light-ingress](./modules/llm-stack/helm/cpu/cpu-tinyllama-light-ingress-tpl) | [gpu-tinyllama-light-ingress](./modules/llm-stack/helm/gpu/gpu-tinyllama-light-ingress-tpl)

---

## 💡 Hardware Options

You can choose to deploy VLLM production stack on either CPU or GPU using the `inference_hardware` parameter
<div align="center">
<img width="703" height="676"  alt="image" src="https://github.com/user-attachments/assets/20a719c9-7a7e-4689-8b15-acfd84448f21" />
<p><em>Figure-2 dependency chain of vllm stack cpu resource</em></p>
</div>

<div align="center">

| Mode | Setting | Resources |
|------|---------|-----------|
| **CPU** | `inference_hardware = "cpu"` | Uses existing CPU nodes (t3a.large) |
| **GPU** | `inference_hardware = "gpu"` | Provisions GPU nodes (g5.xlarge + NVIDIA operator) |

</div>

## 🖥️ AWS GPU Instance Types Available

(T4 · L4 · V100 · A10G · A100) . Read the full list of AWS GPU instance offering [here](https://instances.vantage.sh/?id=f7932a1aadf6b5f3810c902c0e155052f5095bbb).
<details><summary><b> Available GPU instances</b></summary>
<br>

| AWS EC2 Instance | vCPUs | Memory (GiB) | GPUs | GPU Memory (GiB) | Best For |
|---|---|---|---|---|---|
| **NVIDIA Tesla T4** |
| `g4dn.xlarge`   | 4  | 16  | 1 | 16 | Small inference |
| `g4dn.2xlarge`  | 8  | 32  | 1 | 16 | Medium inference |
| `g4dn.4xlarge`  | 16 | 64  | 1 | 16 | Large inference |
| `g4dn.12xlarge` | 48 | 192 | 4 | 64 | Multi-GPU inference |
| **NVIDIA L4** |
| `g6.xlarge`   | 4  | 16  | 1 | 24 | Cost-effective inference |
| `g6.2xlarge`  | 8  | 32  | 1 | 24 | Balanced inference workloads |
| `g6.4xlarge`  | 16 | 64  | 1 | 24 | Large-scale inference |
| **NVIDIA Tesla V100** |
| `p3.2xlarge`  | 8  | 61  | 1 | 16 | Training & inference |
| `p3.8xlarge`  | 32 | 244 | 4 | 64 | Multi-GPU training |
| `p3.16xlarge` | 64 | 488 | 8 | 128 | Large-scale training |
| **NVIDIA A100** |
| `p4d.24xlarge` | 96 | 1 152 | 8 | 320 | Large-scale AI training |
| **NVIDIA A10G** |
| `g5.xlarge`   | 4  | 16  | 1 | 24 | General GPU workloads |
| `g5.2xlarge`  | 8  | 32  | 1 | 24 | Medium GPU workloads |
| `g5.4xlarge`  | 16 | 64  | 1 | 24 | Large GPU workloads |
| `g5.8xlarge`  | 32 | 128 | 1 | 24 | Large-scale inference |
| `g5.12xlarge` | 48 | 192 | 4 | 96 | Multi-GPU training |
| `g5.24xlarge` | 96 | 384 | 4 | 96 | Ultra-large-scale training |
| `g5.48xlarge` | 192| 768 | 8 | 192| Extreme-scale training |

</details>

## GPU Specifications

| GPU Type           |  Best For                         | Relative Cost |
|--------------------|----------------------------------|---------------|
| NVIDIA Tesla T4    | ML inference, small-scale training | $             |
| NVIDIA L4          | Cost-effective inference, edge AI | $             |
| NVIDIA A10G        | Balanced GPU workloads           | $$            |
| NVIDIA Tesla V100  | Large-scale ML training & inference | $$$           |
| NVIDIA A100        | Cutting-edge AI workloads        | $$$$          |

## 🛠️Configuration knobs

This stack provides extensive customization options to tailor your deployment:

| Variable               | Default        | Description                 |
|------------------------|----------------|-----------------------------|
| `region`               | `us-east-2`    | AWS Region                 |
| `pod_cidr`             | `192.168.0.0/16` | Calico Pod overlay network        |
| `inference_hardware`   | `cpu \| gpu`   | Select node pools           |
| `enable_efs_csi_driver`| `true`         | Shared storage              |
| `enable_vllm`          | `true`         | Deploy stack                |
| `hf_token`             | **«secret»**   | HF model download token     |
| `enable_prometheus`    |  true          | prometheus-grafana stack    |
| `cluster_version` | `1.30` | Kubernetes version |
| `nvidia_setup` | `plugin` | GPU setup mode (plugin/operator) |

### 📋 Complete Configuration Options

**This is just a subset of available variables.** For the full list of 20+ configurable options including:

* **Node group** sizing (CPU/GPU pools)
* **Storage drivers** (EBS/EFS)
* **Observability stack** (Prometheus/Grafana)
* **Security settings** (cert-manager, external-secrets)
* **Network configuration** (VPC CIDR, subnets)

**📓** See the complete configuration template:

* **Environment variables**: [`env-vars.template`](./env-vars.template)
* **Terraform variables tfvars**: [`terraform.tfvars.template`](./terraform.tfvars.template)

<details><summary><b> Full list of variables</b></summary>

## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | >= 5.70 |
| <a name="requirement_helm"></a> [helm](#requirement\_helm) | >= 2.15 |
| <a name="requirement_kubectl"></a> [kubectl](#requirement\_kubectl) | >= 1.19.0 |
| <a name="requirement_kubernetes"></a> [kubernetes](#requirement\_kubernetes) | >= 2.32 |
| <a name="requirement_local"></a> [local](#requirement\_local) | >= 2.5 |
| <a name="requirement_random"></a> [random](#requirement\_random) | ~> 3.6 |
| <a name="requirement_tls"></a> [tls](#requirement\_tls) | ~> 4.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | 5.100.0 |
| <a name="provider_helm"></a> [helm](#provider\_helm) | 2.17.0 |
| <a name="provider_kubectl"></a> [kubectl](#provider\_kubectl) | 1.19.0 |
| <a name="provider_kubernetes"></a> [kubernetes](#provider\_kubernetes) | 2.38.0 |
| <a name="provider_local"></a> [local](#provider\_local) | 2.5.3 |
| <a name="provider_template"></a> [template](#provider\_template) | 2.2.0 |
| <a name="provider_time"></a> [time](#provider\_time) | 0.13.1 |

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_data_addons"></a> [data\_addons](#module\_data\_addons) | ./modules/eks-data-addons | n/a |
| <a name="module_eks"></a> [eks](#module\_eks) | ./modules/aws-eks | n/a |
| <a name="module_eks_addons"></a> [eks\_addons](#module\_eks\_addons) | ./modules/eks-blueprints-addons | n/a |
| <a name="module_vpc"></a> [vpc](#module\_vpc) | ./modules/aws-networking/aws-vpc | n/a |

## Resources

| Name | Type |
|------|------|
| [aws_efs_file_system.eks-efs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_file_system) | resource |
| [aws_efs_mount_target.eks-efs-mounts](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_mount_target) | resource |
| [aws_eks_access_entry.developer](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/eks_access_entry) | resource |
| [aws_iam_policy.eks_console_access](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_role.developer](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy_attachment.developer_eks_console_access](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_security_group.efs-sg](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [helm_release.calico](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [helm_release.vllm_stack](https://registry.terraform.io/providers/hashicorp/helm/latest/docs/resources/release) | resource |
| [kubectl_manifest.cluster_role_binding_reader](https://registry.terraform.io/providers/gavinbunney/kubectl/latest/docs/resources/manifest) | resource |
| [kubectl_manifest.cluster_role_reader](https://registry.terraform.io/providers/gavinbunney/kubectl/latest/docs/resources/manifest) | resource |
| [kubectl_manifest.vllm_service_monitor](https://registry.terraform.io/providers/gavinbunney/kubectl/latest/docs/resources/manifest) | resource |
| [kubernetes_config_map.vllm_dashboard](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/config_map) | resource |
| [kubernetes_namespace.vllm](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/namespace) | resource |
| [kubernetes_secret.hf_token](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/secret) | resource |
| [kubernetes_storage_class.gp3](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/storage_class) | resource |
| [kubernetes_storage_class_v1.eks-efs-sc](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/resources/storage_class_v1) | resource |
| [local_file.kubeconfig](https://registry.terraform.io/providers/hashicorp/local/latest/docs/resources/file) | resource |
| [time_sleep.wait_for_addons](https://registry.terraform.io/providers/hashicorp/time/latest/docs/resources/sleep) | resource |
| [aws_availability_zones.available](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/availability_zones) | data source |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_kms_key.eks_managed_key](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/kms_key) | data source |
| [aws_subnet.cluster_public_subnets](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet) | data source |
| [aws_subnet.cluster_subnets](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnet) | data source |
| [aws_subnets.existing_private](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnets) | data source |
| [aws_subnets.existing_public](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/subnets) | data source |
| [aws_vpc.existing](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc) | data source |
| [aws_vpc.selected](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/vpc) | data source |
| [kubernetes_ingress_v1.vllm_ingress](https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs/data-sources/ingress_v1) | data source |
| [template_file.calico_values](https://registry.terraform.io/providers/hashicorp/template/latest/docs/data-sources/file) | data source |
| [template_file.vllm_values](https://registry.terraform.io/providers/hashicorp/template/latest/docs/data-sources/file) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_api_private_access"></a> [api\_private\_access](#input\_api\_private\_access) | n/a | `bool` | `true` | no |
| <a name="input_api_public_access"></a> [api\_public\_access](#input\_api\_public\_access) | API endpoint exposure | `bool` | `true` | no |
| <a name="input_api_public_access_cidrs"></a> [api\_public\_access\_cidrs](#input\_api\_public\_access\_cidrs) | n/a | `list(string)` | <pre>[<br/>  "0.0.0.0/0"<br/>]</pre> | no |
| <a name="input_aws_profile"></a> [aws\_profile](#input\_aws\_profile) | AWS profile to use | `string` | `"cloudthrill"` | no |
| <a name="input_calico_values_file"></a> [calico\_values\_file](#input\_calico\_values\_file) | n/a | `string` | `"modules/eks-data-addons/helm-charts/calico/calico-values.yaml"` | no |
| <a name="input_calico_version"></a> [calico\_version](#input\_calico\_version) | n/a | `string` | `"3.27.2"` | no |
| <a name="input_cluster_name"></a> [cluster\_name](#input\_cluster\_name) | EKS cluster name. | `string` | `"vllm-eks"` | no |
| <a name="input_cluster_version"></a> [cluster\_version](#input\_cluster\_version) | Kubernetes version. | `string` | `"1.30"` | no |
| <a name="input_cpu_node_desired_size"></a> [cpu\_node\_desired\_size](#input\_cpu\_node\_desired\_size) | n/a | `number` | `2` | no |
| <a name="input_cpu_node_instance_types"></a> [cpu\_node\_instance\_types](#input\_cpu\_node\_instance\_types) | n/a | `list(string)` | <pre>[<br/>  "t3.xlarge"<br/>]</pre> | no |
| <a name="input_cpu_node_max_size"></a> [cpu\_node\_max\_size](#input\_cpu\_node\_max\_size) | n/a | `number` | `2` | no |
| <a name="input_cpu_node_min_size"></a> [cpu\_node\_min\_size](#input\_cpu\_node\_min\_size) | n/a | `number` | `1` | no |
| <a name="input_cpu_vllm_helm_config"></a> [cpu\_vllm\_helm\_config](#input\_cpu\_vllm\_helm\_config) | Path to the Helm chart values template for CPU inference. | `string` | `"modules/llm-stack/helm/cpu/cpu-tinyllama-light-ingress.tpl"` | no |
| <a name="input_create_vpc"></a> [create\_vpc](#input\_create\_vpc) | Create a new VPC (true) or reuse an existing one (false). | `bool` | `true` | no |
| <a name="input_enable_cert_manager"></a> [enable\_cert\_manager](#input\_enable\_cert\_manager) | n/a | `bool` | `true` | no |
| <a name="input_enable_cert_manager_cluster_issuer"></a> [enable\_cert\_manager\_cluster\_issuer](#input\_enable\_cert\_manager\_cluster\_issuer) | n/a | `bool` | `true` | no |
| <a name="input_enable_cloudwatch"></a> [enable\_cloudwatch](#input\_enable\_cloudwatch) | Enable AWS Cloudwatch Metrics add-on for Container Insights | `bool` | `false` | no |
| <a name="input_enable_cluster_creator_admin_permissions"></a> [enable\_cluster\_creator\_admin\_permissions](#input\_enable\_cluster\_creator\_admin\_permissions) | Enable admin permissions for the cluster creator. | `bool` | `true` | no |
| <a name="input_enable_dns_hostnames"></a> [enable\_dns\_hostnames](#input\_enable\_dns\_hostnames) | n/a | `bool` | `true` | no |
| <a name="input_enable_dns_support"></a> [enable\_dns\_support](#input\_enable\_dns\_support) | n/a | `bool` | `true` | no |
| <a name="input_enable_ebs_csi_driver"></a> [enable\_ebs\_csi\_driver](#input\_enable\_ebs\_csi\_driver) | n/a | `bool` | `true` | no |
| <a name="input_enable_efs_csi_driver"></a> [enable\_efs\_csi\_driver](#input\_enable\_efs\_csi\_driver) | n/a | `bool` | `false` | no |
| <a name="input_enable_efs_storage"></a> [enable\_efs\_storage](#input\_enable\_efs\_storage) | Enable EFS storage resources for debugging | `bool` | `false` | no |
| <a name="input_enable_external_dns"></a> [enable\_external\_dns](#input\_enable\_external\_dns) | Enable external-dns operator add-on | `bool` | `false` | no |
| <a name="input_enable_external_secrets"></a> [enable\_external\_secrets](#input\_enable\_external\_secrets) | n/a | `bool` | `true` | no |
| <a name="input_enable_grafana"></a> [enable\_grafana](#input\_enable\_grafana) | n/a | `bool` | `true` | no |
| <a name="input_enable_iam_roles"></a> [enable\_iam\_roles](#input\_enable\_iam\_roles) | Enable IAM role resources for debugging | `bool` | `false` | no |
| <a name="input_enable_karpenter"></a> [enable\_karpenter](#input\_enable\_karpenter) | Enable Karpenter controller add-on | `bool` | `false` | no |
| <a name="input_enable_kube_prometheus_stack"></a> [enable\_kube\_prometheus\_stack](#input\_enable\_kube\_prometheus\_stack) | Enable Kube Prometheus Stack | `bool` | `true` | no |
| <a name="input_enable_lb_ctl"></a> [enable\_lb\_ctl](#input\_enable\_lb\_ctl) | Enable AWS Load Balancer Controller add-on | `bool` | `true` | no |
| <a name="input_enable_metrics_server"></a> [enable\_metrics\_server](#input\_enable\_metrics\_server) | n/a | `bool` | `true` | no |
| <a name="input_enable_nat_gateway"></a> [enable\_nat\_gateway](#input\_enable\_nat\_gateway) | n/a | `bool` | `true` | no |
| <a name="input_enable_prometheus"></a> [enable\_prometheus](#input\_enable\_prometheus) | n/a | `bool` | `true` | no |
| <a name="input_enable_vllm"></a> [enable\_vllm](#input\_enable\_vllm) | Enable VLLM production stack add-on | `bool` | `false` | no |
| <a name="input_enable_vpa"></a> [enable\_vpa](#input\_enable\_vpa) | Enable Vertical Pod Autoscaler add-on | `bool` | `false` | no |
| <a name="input_gpu_capacity_type"></a> [gpu\_capacity\_type](#input\_gpu\_capacity\_type) | Choose the GPU capacity type for the GPU node-group.<br/>• "ON\_DEMAND" → use on-demand GPU instances<br/>• "SPOT" → use spot GPU instances | `string` | `"ON_DEMAND"` | no |
| <a name="input_gpu_node_desired_size"></a> [gpu\_node\_desired\_size](#input\_gpu\_node\_desired\_size) | n/a | `number` | `1` | no |
| <a name="input_gpu_node_instance_types"></a> [gpu\_node\_instance\_types](#input\_gpu\_node\_instance\_types) | n/a | `list(string)` | <pre>[<br/>  "g4dn.xlarge"<br/>]</pre> | no |
| <a name="input_gpu_node_max_size"></a> [gpu\_node\_max\_size](#input\_gpu\_node\_max\_size) | n/a | `number` | `1` | no |
| <a name="input_gpu_node_min_size"></a> [gpu\_node\_min\_size](#input\_gpu\_node\_min\_size) | n/a | `number` | `1` | no |
| <a name="input_gpu_operator_file"></a> [gpu\_operator\_file](#input\_gpu\_operator\_file) | Path to GPU Operator Helm values YAML. | `string` | `"modules/llm-stack/helm/gpu/gpu-operator-values.yaml"` | no |
| <a name="input_gpu_vllm_helm_config"></a> [gpu\_vllm\_helm\_config](#input\_gpu\_vllm\_helm\_config) | Path to the Helm chart values template for GPU inference. | `string` | `"modules/llm-stack/helm/gpu/gpu-tinyllama-light-ingress.tpl"` | no |
| <a name="input_hf_token"></a> [hf\_token](#input\_hf\_token) | Hugging Face access token with model-download scope | `string` | n/a | yes |
| <a name="input_inference_hardware"></a> [inference\_hardware](#input\_inference\_hardware) | Choose the hardware profile for inference workloads.<br/>• "cpu" → only the default CPU node‑group<br/>• "gpu" → CPU node‑group + a GPU node‑group (g4dn.xlarge, 1 node) | `string` | `"cpu"` | no |
| <a name="input_letsencrypt_email"></a> [letsencrypt\_email](#input\_letsencrypt\_email) | n/a | `string` | `"admin@example.com"` | no |
| <a name="input_nvidia_setup"></a> [nvidia\_setup](#input\_nvidia\_setup) | GPU enablement strategy:<br/>  • "plugin"           → installs only the nvidia-device-plugin DaemonSet<br/>  • "operator\_custom"  → GPU Operator with your YAML values file<br/>  • "operator\_no\_driver" → GPU Operator, driver & toolkit pods disabled (map-style set) | `string` | `"plugin"` | no |
| <a name="input_one_nat_gateway_per_az"></a> [one\_nat\_gateway\_per\_az](#input\_one\_nat\_gateway\_per\_az) | n/a | `bool` | `false` | no |
| <a name="input_pod_cidr"></a> [pod\_cidr](#input\_pod\_cidr) | Pod network CIDR. | `string` | `"10.244.0.0/16"` | no |
| <a name="input_private_subnet_cidrs"></a> [private\_subnet\_cidrs](#input\_private\_subnet\_cidrs) | CIDRs for private subnets. | `list(string)` | <pre>[<br/>  "10.20.1.0/24",<br/>  "10.20.2.0/24",<br/>  "10.20.3.0/24"<br/>]</pre> | no |
| <a name="input_public_subnet_cidrs"></a> [public\_subnet\_cidrs](#input\_public\_subnet\_cidrs) | CIDRs for public subnets. | `list(string)` | <pre>[<br/>  "10.20.101.0/24",<br/>  "10.20.102.0/24",<br/>  "10.20.103.0/24"<br/>]</pre> | no |
| <a name="input_region"></a> [region](#input\_region) | AWS region where all resources are deployed. | `string` | `"us-east-2"` | no |
| <a name="input_single_nat_gateway"></a> [single\_nat\_gateway](#input\_single\_nat\_gateway) | n/a | `bool` | `true` | no |
| <a name="input_tags"></a> [tags](#input\_tags) | Tags applied to all AWS resources. | `map(string)` | <pre>{<br/>  "Application": "ai-inference",<br/>  "CostCenter": "AI-1234",<br/>  "Environment": "production",<br/>  "Project": "vllm-production-stack",<br/>  "Team": "LLMOps"<br/>}</pre> | no |
| <a name="input_vpc_cidr"></a> [vpc\_cidr](#input\_vpc\_cidr) | CIDR block for the VPC. | `string` | `"10.20.0.0/16"` | no |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | Existing VPC ID (required when create\_vpc = false). | `string` | `""` | no |
| <a name="input_vpc_name"></a> [vpc\_name](#input\_vpc\_name) | Name for the VPC. | `string` | `"vllm-vpc"` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_Stack_Info"></a> [Stack\_Info](#output\_Stack\_Info) | n/a |
| <a name="output_cluster_endpoint"></a> [cluster\_endpoint](#output\_cluster\_endpoint) | n/a |
| <a name="output_cluster_name"></a> [cluster\_name](#output\_cluster\_name) | n/a |
| <a name="output_cluster_public_subnets_info"></a> [cluster\_public\_subnets\_info](#output\_cluster\_public\_subnets\_info) | Information about public subnets used by the EKS cluster |
| <a name="output_cluster_subnets_info"></a> [cluster\_subnets\_info](#output\_cluster\_subnets\_info) | Information about private subnets used by the EKS cluster |
| <a name="output_configure_kubectl"></a> [configure\_kubectl](#output\_configure\_kubectl) | Configure kubectl: make sure you're logged in with the correct AWS profile and run the following command to update your kubeconfig |
| <a name="output_cpu_node_instance_type"></a> [cpu\_node\_instance\_type](#output\_cpu\_node\_instance\_type) | Instance types configured for CPU nodes |
| <a name="output_gpu_node_instance_type"></a> [gpu\_node\_instance\_type](#output\_gpu\_node\_instance\_type) | Instance types configured for GPU nodes |
| <a name="output_grafana_forward_cmd"></a> [grafana\_forward\_cmd](#output\_grafana\_forward\_cmd) | Command to forward Grafana port |
| <a name="output_private_subnets"></a> [private\_subnets](#output\_private\_subnets) | n/a |
| <a name="output_public_subnets"></a> [public\_subnets](#output\_public\_subnets) | n/a |
| <a name="output_vllm_api_url"></a> [vllm\_api\_url](#output\_vllm\_api\_url) | Full HTTPS URL for the vLLM API (null until hostname exists) |
| <a name="output_vllm_ingress_hostname"></a> [vllm\_ingress\_hostname](#output\_vllm\_ingress\_hostname) | The hostname of the vLLM ingress load balancer (null if no ingress configured) |
| <a name="output_vpc_cidr"></a> [vpc\_cidr](#output\_vpc\_cidr) | #### Network outputs ##### |
| <a name="output_vpc_id"></a> [vpc\_id](#output\_vpc\_id) | n/a |

</details>

---

## 🚀 Quick start

### ⚙️ Provisioning logic

The deployment automatically provisions only the required infrastructure based on your hardware selection.

| Phase | Component | Action | Condition |
|-------|-----------|--------|-----------|
| **1. Infrastructure** | VPC | Provision VPC with 3 public + 3 private subnets | Always |
| | EKS | Deploy v1.30 cluster + CPU node group (t3a.large) | Always |
| | CNI | Remove aws-node, install Calico overlay (VXLAN) | Always |
| | Add-ons | Deploy EBS CSI, ALB controller, kube-prometheus | Always |
| **2. vLLM Stack** | | | `enable_vllm = true` |
| | HF secret| Deploy Create `hf-token-secret` for Hugging Face | `enable_vllm = true` |
| | CPU Deployment | Deploy vLLM on existing CPU nodes | `inference_hardware = "cpu"` |
| | GPU Infrastructure | Provision GPU node group (g5.xlarge) | `inference_hardware = "gpu"` |
| | GPU Operator | Deploy NVIDIA operator/plugin | `inference_hardware = "gpu"` |
| | GPU Deployment | Deploy vLLM on GPU nodes with scheduling | `inference_hardware = "gpu"` |
| | Application | Deploy TinyLlama-1.1B Helm chart to `vllm` namespace | `enable_vllm = true` |
| **3. Networking** | Load Balancer | Configure ALB and ingress for external access | `enable_vllm = true` |
| **4. model storage** | loaded locally | Using init container | -> `/data/models` |

---

## 🔵 Deployment Steps

### 1. Clone the repository

```bash
git clone https://github.com/vllm-project/production-stack
cd production-stack/tutorials/terraform/eks/
```

### 2. Configure the Environment

```bash
cp env-vars.template env-vars
vim env-vars  # Set HF token and customize deployment options
source env-vars
```

**Usage examples**

* **Option 1: Through Environment Variables**

  ```bash
  # Copy and customize
  $ cp env-vars.template env-vars
  $ vi env-vars
  ################################################################################
  # EKS Cluster Configuration
  ################################################################################
  # ☸️ EKS cluster basics
  export TF_VAR_cluster_name="vllm-eks-prod" # default: "vllm-eks-prod"
  export TF_VAR_cluster_version="1.30"       # default: "1.30" - Kubernetes cluster version
   ################################################################################
   # 🤖 NVIDIA setup selector
   #   • plugin           -> device-plugin only
   #   • operator_no_driver -> GPU Operator (driver disabled)
   #   • operator_custom  -> GPU Operator with your YAML
   ################################################################################
   export TF_VAR_nvidia_setup="plugin" # default: "plugin"
   ################################################################################
   # 🧠 LLM Inference Configuration
   ################################################################################
   export TF_VAR_enable_vllm="true"         # default: "false" - Set to "true" to deploy vLLM
   export TF_VAR_hf_token=""                # default: "" - Hugging Face token for model download (if needed)
   export TF_VAR_inference_hardware="gpu"   # default: "cpu" - "cpu" or "gpu"
   ################################################################################
   export TF_VAR_nvidia_setup="plugin" # default: ""
   # Paths to Helm chart values templates for vLLM.
   # These paths are relative to the root of your Terraform project.
   export TF_VAR_gpu_vllm_helm_config="./modules/llm-stack/helm/gpu/gpu-tinyllama-light-ingress.tpl" # default: ""
   export TF_VAR_cpu_vllm_helm_config="./modules/llm-stack/helm/cpu/cpu-tinyllama-light-ingress.tpl" # default: ""
   ################################################################################
   # ⚙️ Node-group sizing
   ################################################################################
   # CPU pool (always present)
   export TF_VAR_cpu_node_min_size="1"     # default: 1
   export TF_VAR_cpu_node_max_size="3"     # default: 3
   export TF_VAR_cpu_node_desired_size="2" # default: 2
   # GPU pool (ignored unless inference_hardware = "gpu")
   export TF_VAR_gpu_node_min_size="1"     # default: 1
   export TF_VAR_gpu_node_max_size="1"     # default: 1
   export TF_VAR_gpu_node_desired_size="1" # default: 1
   ...snip
   $ source env-vars
   ```

* **Option 2: Through Terraform Variables**

  ```bash
   # Copy and customize
   $ cp terraform.tfvars.example terraform.tfvars
   $ vim terraform.tfvars
  ```

### 3. Deploy Infrastructure

```bash
terraform init
terraform plan
terraform apply
```

---

## 🧪 Quick Test

**1. Router Endpoint and API URL**

1.1 **Router Endpoint through port forwarding**
   run the following command:

```bash
kubectl -n vllm port-forward svc/vllm-gpu-router-service 30080:80

```

1.2 **Extracting the Router URL via AWS ALB Ingress**
If AWS load balancer Controller is enabled (`enable_lb_ctl=true`), The router endpoint ingress URL is displayed in the `vllm_ingress_hostname` output, or by running the following command:

```bash
$ k get ingress -n vllm -o json| jq -r .items[0].status.loadBalancer.ingress[].hostname
k8s-vllm-vllmingr-983dc8fd68-161738753.us-east-2.elb.amazonaws.com
```

**2. List models**

```bash
-- case 1 : Port forwarding
export vllm_api_url=http://localhost:30080/v1
-- case 2 : AWS ALB Ingress enabled
export vllm_api_url=http://k8s-vllm-vllmingr-983dc8fd68-161738753.us-east-2.elb.amazonaws.com/v1

---- check models
curl -s ${vllm_api_url}/models | jq .
```

**3. Completion**
Applicable for both ingress and port forwarding URLs

```bash
curl ${vllm_api_url}/completions     -H "Content-Type: application/json"     -d '{
        "model": "/data/models/tinyllama",
        "prompt": "Toronto is a",
        "max_tokens": 20,
        "temperature": 0
    }'| jq .choices[].text


//*
"city that is known for its vibrant nightlife, and there are plenty of bars and clubs"
//*

```

**5. vLLM model service**

```bash
kubectl -n vllm get svc
```

## 🔬 Observability

Grafana (if enabled) you can use port forwarding to access the dashboard. URL → "<http://localhost:3000>"

 ```bash
 kubectl port-forward svc/kube-prometheus-stack-grafana 3000:80 -n kube-prometheus-stack
 ```

* Login: admin
* Run the below command to fetch the password

```bash
kubectl get secret -n kube-prometheus-stack kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 --decode
```

>[!note]
> In this stack, the vLLM dashboard and service monitoring are automatically configured in Grafana. No manual setup needed.
><img width="3813" height="1643" alt="image" src="https://github.com/user-attachments/assets/2df312b6-3465-4049-90c8-c33540f5b6d3" />

---

## 🎯 Troubleshooting

**1. [Ordering issue with AWS Load Balancer Controller](https://github.com/aws-ia/terraform-aws-eks-blueprints-addons/issues/233)**

With LBC ≥ 2.5.1 the chart enables a MutatingWebhook that intercepts every Service of type LoadBalancer:
<img width="2162" height="433" alt="image" src="https://github.com/user-attachments/assets/10e00422-436b-4003-a6de-e1edee912da7" />

As a result addons services (i.e cert manager) will timeout waiting for the webhook to be available.

```bash
no endpoints available for service "aws-load-balancer-webhook-service"
```

> **Fix Applied**
>
> We turned off the webhook as we don't use `serviceType: LoadBalancer`here.
>
> ```bash
> # in your blueprints-addons block
> aws_load_balancer_controller = {
>  enable_service_mutator_webhook = false   # turns off the webhook
>}
> ```
>
> **Note:** If you plan to use `serviceType: LoadBalancer`, deploy the LBC add-on first, then apply the rest of the stack.

**2. Calico discovery commands**

```bash
# Calico pods (overlay CNI)
kubectl -n tigera-operator get pods
# 1. kubectl get all -n tigera-operator
# 2. kubectl get installation -o yaml | yq '.items[].spec.cni.type'
# 3. kubectl get ds -n calico-system -w
# 4. kubectl get tigerastatus
```

## 🔧 Cleanup Notes

### Optional Manual Cleanup

In rare cases, you may need to manually clean up some AWS resources while running terraform destroy. Here are the most common scenarios:

**1️⃣. load balancer blocking public subnets/igw deletion**

When AWS LB controller ingress is enabled (`enable_lb_ctl=true`), you might encounter VPC deletion issues linked to LB dependency. Run the below cleanup commands:

```bash
export PROFILE=profile_name  (ex: default)
export region=<region>       (ex: "us-east-2")
 # 1. Clean up load balancer
alb_name=`aws elbv2 describe-load-balancers --query "LoadBalancers[*].LoadBalancerName" --output text --profile $PROFILE`
 alb_arn=$(aws elbv2 describe-load-balancers \
   --names  $alb_name \
  --query 'LoadBalancers[0].LoadBalancerArn' \
  --output text --region $region --profile $PROFILE)
# delete :
aws elbv2 delete-load-balancer --load-balancer-arn "$alb_arn" --region $region --profile $PROFILE
```

**Re-Run terraform destroy**

``` bash
terraform destroy
```

>[!note]
> Another solution is to disable AWS load balancer control creation altogether by setting the variable `enable_lb_ctl` to `false` see  [variables.tf](./variables.tf)

**2️⃣. vllm namespace**

When AWS LB controller ingress is enabled (`enable_lb_ctl=true`),the vLLM namespace can get stuck in "Terminating" state, you might need to patch some finalizers.

```bash
# Remove finalizers from AWS resources
RESOURCE_NAME=$(kubectl get targetgroupbinding.elbv2.k8s.aws -n vllm -o jsonpath='{.items[0].metadata.name}')
kubectl patch targetgroupbinding.elbv2.k8s.aws $RESOURCE_NAME -n vllm --type=merge -p '{"metadata":{"finalizers":[]}}'
-- the delete might not be needed
kubectl delete targetgroupbinding.elbv2.k8s.aws $RESOURCE_NAME -n vllm --ignore-not-found=true
INGRESS_NAME=$(kubectl get ingress -n vllm -o jsonpath='{.items[0].metadata.name}')
kubectl patch ingress $INGRESS_NAME -n vllm --type=merge -p '{"metadata":{"finalizers":[]}}'
```

**3️⃣. Calico Cleanup Jobs**

If encountering job conflicts during Calico removal (i.e: * jobs.batch "tigera-operator-uninstall" already exists) run the below commands

```bash
# use the following commands to delete the jobs manually first:
kubectl -n tigera-operator delete job tigera-operator-uninstall --ignore-not-found=true
kubectl -n tigera-operator delete job tigera-operator-delete-crds --ignore-not-found=true
kubectl delete ns tigera-operator --ignore-not-found=true
```

**4️⃣. Clean up associated security groups**
When AWS LB controller ingress is enabled (`enable_lb_ctl=true`), you might need to  delete orphan SGs (non-default) to destroy subnets:

```bash
VPC_ID=$(aws ec2 describe-vpcs --query 'Vpcs[?Tags[?Key==`Name` && Value==`vllm-vpc`]].VpcId' --output text --profile $PROFILE)
# Deletion
aws ec2 describe-security-groups --filters Name=vpc-id,Values=${VPC_ID} --query "SecurityGroups[?starts_with(GroupName, 'k8s-') || contains(GroupName, 'vllm')].GroupId"    --output text    --profile ${PROFILE} |  tr -s '[:space:]' '\n' |  xargs -r -I{} aws ec2 delete-security-group --group-id {} --profile ${PROFILE}
```

**Note:** These manual steps are only needed if terraform destroy encounters specific dependency issues.

## 📚 Additional Resources

* [vLLM Documentation](https://docs.vllm.ai/)
* [terraform-aws-eks](https://github.com/terraform-aws-modules/terraform-aws-eks)
* [EKS Blueprints](https://github.com/aws-ia/terraform-aws-eks-blueprints)
* [Calico Documentation](https://docs.projectcalico.org/)
* [AWS Load Balancer Controller](https://kubernetes-sigs.github.io/aws-load-balancer-controller/)
<!-- markdownlint-disable MD051 MD036 MD056 -->
