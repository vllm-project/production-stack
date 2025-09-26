## -------------------------------------------------------------------------------------------
##  Author: Kosseila HD (@CloudThrill)
##  License: MIT
##  Date: Summer 2025
##  Description: VPC and networking resources for EKS cluster.
## -------------------------------------------------------------------------------------------
############################
# Create or use existing VPC
############################
locals {
  # Values: true = create, false = reuse
  create_new_vpc = var.create_vpc
  public_names  = [for az in local.azs : "${var.vpc_name}-sub-pub-${az}"]
  private_names = [for az in local.azs : "${var.vpc_name}-sub-priv-${az}"]
}

############################
# Always call the module
############################
module "vpc" {
  source          = "git::https://github.com/cloudthrill/terraform-aws-eks-modules.git//aws-networking/aws-vpc?ref=v1.0.0"
  create_vpc      = local.create_new_vpc
  name            = var.vpc_name
  cidr            = var.vpc_cidr
  azs             = local.azs
  public_subnets  = var.public_subnet_cidrs
  private_subnets = var.private_subnet_cidrs
  # Dynamic calculation ensures subnets always match VPC CIDR
  # public_subnets  = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 8, k + 100)]
  # private_subnets = [for k, v in local.azs : cidrsubnet(var.vpc_cidr, 8, k)]
  enable_nat_gateway     = var.enable_nat_gateway
  single_nat_gateway     = var.single_nat_gateway
  one_nat_gateway_per_az = var.one_nat_gateway_per_az
  enable_dns_hostnames   = var.enable_dns_hostnames
  enable_dns_support     = var.enable_dns_support

  # The blueprint uses Kubernetes-specific subnet tags:
  public_subnet_names  = local.public_names
  private_subnet_names = local.private_names
  public_subnet_tags = {
  #  for idx, az in local.azs : {
    "kubernetes.io/role/elb"                    = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "owned"
  # "Name" = "${var.tags.Project}-publicsub${az}" }
  }
#  merge(var.tags, {
#   "kubernetes.io/role/elb"                    = 1
#   "kubernetes.io/cluster/${var.cluster_name}" = "owned"
# })

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb"           = 1
    "kubernetes.io/cluster/${var.cluster_name}" = "owned"
   # "Name" = "${var.tags.Project}-privatesub${az}"
  }

  tags = var.tags
}

#################################
# Look-ups only when reusing VPC
#################################
data "aws_vpc" "existing" {
  count = local.create_new_vpc ? 0 : 1
  id    = var.vpc_id
}

data "aws_subnets" "existing_private" {
  count = local.create_new_vpc ? 0 : 1
  filter {
    name   = "tag:kubernetes.io/role/internal-elb"
    values = ["1"]
  }
  # Uncomment and adjust tags as needed
  # tags = { Tier = "private" }
}

# For existing public subnets
data "aws_subnets" "existing_public" {
  count = local.create_new_vpc ? 0 : 1
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "tag:kubernetes.io/role/elb"
    values = ["1"]
  }
}
############################
# Single set of IDs (OCI style)
############################
locals {
  vpc_id             = local.create_new_vpc ? module.vpc.vpc_id : data.aws_vpc.existing[0].id
  private_subnet_ids = local.create_new_vpc ? module.vpc.private_subnets : data.aws_subnets.existing_private[0].ids
  public_subnet_ids  = local.create_new_vpc ? module.vpc.public_subnets : data.aws_subnets.existing_public[0].ids
}


# 💡Destroy tips
# If you face terraform destroy issues because of a Load Balancer creation outside terraform,
# use the following commands to delete the ALB manually first:
# 1. load balancer blocking public subnets/igw deletion
# aws elbv2 describe-load-balancers --query "LoadBalancers[*].{Name:LoadBalancerName,Type:Type,State:State.Code,DNSName:DNSName}" --output table --profile myprofile
# alb_name=`aws elbv2 describe-load-balancers --query "LoadBalancers[*].LoadBalancerName" --output text`
# alb_arn=$(aws elbv2 describe-load-balancers --names $alb_name --query 'LoadBalancers[0].LoadBalancerArn' \
#   --output text --region <region> --profile <default>)

# aws elbv2 delete-load-balancer --load-balancer-arn "$alb_arn" \
#   --region <region> --profile profile_name
# then run terraform destroy again.

# 2. security groups
# aws ec2 describe-vpcs --query 'Vpcs[*].{ID:VpcId,Name:Tags[?Key==`Name`].Value|[0]}' --output text --profile yourprofile
# VPC_ID=$(aws ec2 describe-vpcs --query 'Vpcs[?Tags[?Key==`Name` && Value==`vllm-vpc`]].VpcId' --output text --profile yourprofile)
# aws ec2 describe-security-groups \
#   --filters Name=vpc-id,Values=${VPC_ID} \
#   --query "SecurityGroups[
#              ? !contains(GroupName, \`default\`) &&
#                (contains(Description, \`ELB\`) ||
#                 contains(Description, \`Load Balancer\`) ||
#                 starts_with(GroupName, \`k8s-\`))
#            ].GroupId" \
#   --output text
#   --profile ${PROFILE} | \
# xargs -r -I{} aws ec2 delete-security-group --group-id {} --profile ${PROFILE}
## vllm
# PROFILE="cloudthrill"
# aws ec2 describe-security-groups \
#   --filters Name=vpc-id,Values=${VPC_ID} \
#   --query "SecurityGroups[?starts_with(GroupName, 'k8s-') || contains(GroupName, 'vllm')].GroupId" \
#   --output text \
#   --profile ${PROFILE} | \
# tr -s '[:space:]' '\n' | \
# xargs -r -I{} aws ec2 delete-security-group --group-id {} --profile ${PROFILE}
# one liner
#  aws ec2 describe-security-groups --filters Name=vpc-id,Values=${VPC_ID}    --query "SecurityGroups[?starts_with(GroupName, 'k8s-') || contains(GroupName, 'vllm')].GroupId"    --output text    --profile ${PROFILE} |  tr -s '[:space:]' '\n' |  xargs -r -I{} aws ec2 delete-security-group --group-id {} --profile ${PROFILE}
# manually
# aws ec2 describe-security-groups --filters "Name=vpc-id,Values=${VPC_ID}" --query "SecurityGroups[].{id:GroupId, GroupName:GroupName}" --profile yourProfile
# Calico :
# kubectl patch namespace calico-system --type=merge -p '{"metadata":{"finalizers":null}}'
# kubectl get namespace tigera-operator -o yaml -o jsonpath='{.spec.finalizers}'
# ["kubernetes"]
# kubectl patch namespace tigera-operator --type=merge -p '{"spec":{"finalizers":[]}}'
###############################################################
