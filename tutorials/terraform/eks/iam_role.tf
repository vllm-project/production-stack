
resource "aws_iam_role" "developer" {
  count = var.enable_iam_roles ? 1 : 0
  name  = "developer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Condition = {}
      }
    ]
  })
}

resource "aws_iam_policy" "eks_console_access" {
  count = var.enable_iam_roles ? 1 : 0
  name  = "EKSConsoleAccess"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:DescribeNodegroup",
          "eks:DescribeUpdate",
          "eks:AccessKubernetesApi"
        ]
        Resource = [
          "arn:aws:eks:*:${data.aws_caller_identity.current.account_id}:cluster/*",
          "arn:aws:eks:*:${data.aws_caller_identity.current.account_id}:nodegroup/*/*/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "eks:ListClusters",
          "eks:ListNodegroups",
          "eks:ListUpdates"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "developer_eks_console_access" {
  count      = var.enable_iam_roles ? 1 : 0
  role       = aws_iam_role.developer[0].name
  policy_arn = aws_iam_policy.eks_console_access[0].arn
}

# EKS Access Entry - Modern approach  no ComfigMap needed
# This allows the developer role to access the EKS cluster with the "reader" group permissions
resource "aws_eks_access_entry" "developer" {
  count             = var.enable_iam_roles ? 1 : 0
  cluster_name      = module.eks.cluster_name
  principal_arn     = aws_iam_role.developer[0].arn
  kubernetes_groups = ["reader"]
  type              = "STANDARD"

  depends_on = [aws_iam_role_policy_attachment.developer_eks_console_access]
}

# Kubernetes RBAC resources remain the same
resource "kubectl_manifest" "cluster_role_reader" {
  count     = var.enable_iam_roles ? 1 : 0
  yaml_body = <<YAML
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reader
rules:
- apiGroups: ["*"]
  resources: ["deployments", "configmaps", "pods", "secrets", "services"]
  verbs: ["get", "list", "watch"]
YAML

  depends_on = [aws_eks_access_entry.developer]
}

resource "kubectl_manifest" "cluster_role_binding_reader" {
  count     = var.enable_iam_roles ? 1 : 0
  yaml_body = <<YAML
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: reader
subjects:
- kind: Group
  name: reader
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: reader
  apiGroup: rbac.authorization.k8s.io
YAML

  depends_on = [kubectl_manifest.cluster_role_reader]
}
