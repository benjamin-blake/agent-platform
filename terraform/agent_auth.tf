# ============================================================================
# Agent Service Account -- Pattern B static-key identity
#
# DECLARED BUT NOT APPLIED in this plan.
# Per CD.6 (personal-account rebuild-not-migrate), T2.1 is the canonical
# apply/import moment. Console-created resources must be imported:
#   terraform import 'aws_iam_user.agent_service_account' 'agent-service-account'
#   terraform import 'aws_iam_user_policy.agent_service_account_assume_role' \
#     'agent-service-account:AssumeRoleOnly'
#
# The aws_iam_access_key resource tracks the key created via the console.
# Its secret is stored in ~/.aws/credentials as [company-static-profile]; it is NEVER
# committed to this repository.
# ============================================================================

variable "platform_dev_external_id" {
  description = "ExternalId for PlatformDev AssumeRole trust (stored in ~/.aws/sealed/external-ids.json; NOT committed to repo)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "platform_admin_external_id" {
  description = "ExternalId for PlatformAdmin AssumeRole trust (stored in ~/.aws/sealed/external-ids.json; NOT committed to repo)"
  type        = string
  sensitive   = true
  default     = ""
}

resource "aws_iam_user" "agent_service_account" {
  provider = aws.platform
  name     = "agent-service-account"
}

resource "aws_iam_user_policy" "agent_service_account_assume_role" {
  provider = aws.platform
  name     = "AssumeRoleOnly"
  user     = aws_iam_user.agent_service_account.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Resource = [
          aws_iam_role.platform_dev.arn,
          aws_iam_role.platform_admin.arn,
        ]
      }
    ]
  })
}

# Access key is managed here for Terraform state tracking only.
# The actual key material lives in ~/.aws/credentials as [company-static-profile].
resource "aws_iam_access_key" "agent_service_account" {
  provider = aws.platform
  user     = aws_iam_user.agent_service_account.name
}

output "agent_service_account_access_key_id" {
  description = "Access key ID for agent-service-account (key secret is in ~/.aws/credentials [company-static-profile])"
  value       = aws_iam_access_key.agent_service_account.id
  sensitive   = false
}

output "agent_service_account_access_key_secret" {
  description = "Access key secret for agent-service-account -- store in ~/.aws/credentials as [company-static-profile]"
  value       = aws_iam_access_key.agent_service_account.secret
  sensitive   = true
}
