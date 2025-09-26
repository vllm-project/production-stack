
# Create EFS file system and mount targets separately
locals {
  enable_efs_storage = var.enable_efs_storage && var.enable_efs_csi_driver
}

resource "aws_efs_file_system" "eks-efs" {
  count          = local.enable_efs_storage ? 1 : 0
  creation_token = "${var.cluster_name}-efs"

  performance_mode                = "generalPurpose"
  throughput_mode                 = "provisioned"
  provisioned_throughput_in_mibps = 100
  encrypted                       = true
  # lifecycle_policy {
  #   transition_to_ia = "AFTER_30_DAYS"
  # }
  tags = {
    Name = "eks-${var.cluster_name}-efs"
  }
}

# Create mount targets in each private subnet
resource "aws_efs_mount_target" "eks-efs-mounts" {
  count = local.enable_efs_storage ? length(local.private_subnet_ids) : 0
  file_system_id  = aws_efs_file_system.eks-efs[0].id
  subnet_id       = local.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs-sg[0].id, module.eks.cluster_primary_security_group_id]

  # being explicit helps Terraform order things correctly
  depends_on = [
    module.vpc,
    aws_efs_file_system.eks-efs,
  ]
}

###############################################################
# Security group for EFS
##############################################################
resource "aws_security_group" "efs-sg" {
  count       = local.enable_efs_storage ? 1 : 0
  name_prefix = "eks-${var.cluster_name}-efs-"
  vpc_id      = local.vpc_id
  description = "EFS security group for EKS cluster ${var.cluster_name}"
  ingress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "Allow NFS traffic from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.cluster_name}-efs-sg"
  }
}

##############################################################
# Storage class for EFS
##############################################################

resource "kubernetes_storage_class_v1" "eks-efs-sc" {
  count = local.enable_efs_storage ? 1 : 0
  metadata {
    name = "efs-sc"
  }

  storage_provisioner = "efs.csi.aws.com"

  parameters = {
    provisioningMode = "efs-ap"
    fileSystemId     = aws_efs_file_system.eks-efs[0].id
    directoryPerms   = "0755"
  }

  depends_on = [module.eks_addons.aws_efs_csi_driver]
}
