# Personal module variables. account_id has NO default by design: the personal account ID must
# never be a committed literal (PLAN-public-migration Step 11b). It is supplied at apply time from
# the gitignored terraform.personal.tfvars.

variable "aws_region" {
  description = "AWS region for personal-account platform resources"
  type        = string
  default     = "eu-west-2"
}

variable "aws_profile" {
  description = "Provisioning SSO profile (PlatformAdmin role -- creates IAM + OIDC). Runtime code uses agent_platform (PlatformDev)."
  type        = string
  default     = "agent_platform_admin"
}

variable "account_id" {
  description = "Personal AWS account ID. Supplied via gitignored terraform.personal.tfvars -- never committed."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "owner_email" {
  description = "Owner email for resource tagging (GitHub no-reply identity)"
  type        = string
}

variable "platform_dev_external_id" {
  description = "ExternalId for the PlatformDev AssumeRole trust. Supplied via gitignored terraform.personal.tfvars -- never a committed literal."
  type        = string
  sensitive   = true
}

variable "platform_admin_external_id" {
  description = "ExternalId for the PlatformAdmin AssumeRole trust. Supplied via gitignored terraform.personal.tfvars -- never a committed literal."
  type        = string
  sensitive   = true
}

variable "agent_service_account_user_name" {
  description = "IAM user (the agent_static static-key source profile) permitted to assume PlatformDev. Verify against the live role's trust policy via `terraform plan` before apply."
  type        = string
  default     = "agent-service-account"
}
