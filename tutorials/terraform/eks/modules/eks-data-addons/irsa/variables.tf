variable "name" {
  description = "Name of the Helm release"
  type        = string
  default     = ""
}

variable "create" {
  description = "Controls if resources should be created (affects all resources)"
  type        = bool
  default     = true
}

variable "create_role" {
  description = "Whether to create a role"
  type        = bool
  default     = false
}

variable "role_name" {
  description = "Name of IAM role"
  type        = string
  default     = null
}

variable "role_name_use_prefix" {
  description = "Determines whether the IAM role name (`role_name`) is used as a prefix"
  type        = bool
  default     = true
}

variable "role_path" {
  description = "Path of IAM role"
  type        = string
  default     = "/"
}

variable "role_permissions_boundary_arn" {
  description = "Permissions boundary ARN to use for IAM role"
  type        = string
  default     = null
}

variable "role_description" {
  description = "IAM Role description"
  type        = string
  default     = null
}

variable "role_policy_arns" {
  description = "ARNs of any policies to attach to the IAM role"
  type        = map(string)
  default     = {}
}

variable "oidc_providers" {
  description = "Map of OIDC providers where each provider map should contain the `provider_arn`, and `service_accounts`"
  type        = any
  default     = {}
}

variable "force_detach_policies" {
  description = "Whether policies should be detached from this role when destroying"
  type        = bool
  default     = true
}

variable "max_session_duration" {
  description = "Maximum CLI/API session duration in seconds between 3600 and 43200"
  type        = number
  default     = null
}

variable "assume_role_condition_test" {
  description = "Name of the [IAM condition operator](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_condition_operators.html) to evaluate when assuming the role"
  type        = string
  default     = "StringEquals"
}

variable "allow_self_assume_role" {
  description = "Determines whether to allow the role to be [assume itself](https://aws.amazon.com/blogs/security/announcing-an-update-to-iam-role-trust-policy-behavior/)"
  type        = bool
  default     = false
}

variable "tags" {
  description = "A map of tags to add the the IAM role"
  type        = map(any)
  default     = {}
}
