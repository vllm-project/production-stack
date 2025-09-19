################################################################################
# IAM Role for Service Account(s) (IRSA)
################################################################################

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

locals {
  create_role = var.create && var.create_role

  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  role_name           = try(coalesce(var.role_name, var.name), "")
  role_name_condition = var.role_name_use_prefix ? "${local.role_name}-*" : local.role_name
}

data "aws_iam_policy_document" "this" {
  count = local.create_role ? 1 : 0

  dynamic "statement" {
    # https://aws.amazon.com/blogs/security/announcing-an-update-to-iam-role-trust-policy-behavior/
    for_each = var.allow_self_assume_role ? [1] : []

    content {
      sid     = "ExplicitSelfRoleAssumption"
      effect  = "Allow"
      actions = ["sts:AssumeRole"]

      principals {
        type        = "AWS"
        identifiers = ["*"]
      }

      condition {
        test     = "ArnLike"
        variable = "aws:PrincipalArn"
        values   = ["arn:${local.partition}:iam::${local.account_id}:role${var.role_path}${local.role_name_condition}"]
      }
    }
  }

  dynamic "statement" {
    for_each = var.oidc_providers

    content {
      effect  = "Allow"
      actions = ["sts:AssumeRoleWithWebIdentity"]

      principals {
        type        = "Federated"
        identifiers = [statement.value.provider_arn]
      }

      condition {
        test     = var.assume_role_condition_test
        variable = "${replace(statement.value.provider_arn, "/^(.*provider/)/", "")}:sub"
        values   = ["system:serviceaccount:${statement.value.namespace}:${statement.value.service_account}"]
      }

      # https://aws.amazon.com/premiumsupport/knowledge-center/eks-troubleshoot-oidc-and-irsa/?nc1=h_ls
      condition {
        test     = var.assume_role_condition_test
        variable = "${replace(statement.value.provider_arn, "/^(.*provider/)/", "")}:aud"
        values   = ["sts.amazonaws.com"]
      }
    }
  }
}

resource "aws_iam_role" "this" {
  count = local.create_role ? 1 : 0

  name        = var.role_name_use_prefix ? null : local.role_name
  name_prefix = var.role_name_use_prefix ? "${local.role_name}-" : null
  path        = var.role_path
  description = var.role_description

  assume_role_policy    = data.aws_iam_policy_document.this[0].json
  max_session_duration  = var.max_session_duration
  permissions_boundary  = var.role_permissions_boundary_arn
  force_detach_policies = var.force_detach_policies

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = { for k, v in var.role_policy_arns : k => v if local.create_role }

  role       = aws_iam_role.this[0].name
  policy_arn = each.value
}
