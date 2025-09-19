output "iam_role_arn" {
  description = "ARN of IAM role"
  value       = try(aws_iam_role.this[0].arn, null)
}

output "iam_role_name" {
  description = "Name of IAM role"
  value       = try(aws_iam_role.this[0].name, null)
}

output "iam_role_path" {
  description = "Path of IAM role"
  value       = try(aws_iam_role.this[0].path, null)
}

output "iam_role_unique_id" {
  description = "Unique ID of IAM role"
  value       = try(aws_iam_role.this[0].unique_id, null)
}
