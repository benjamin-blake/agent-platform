# ============================================================================
# Platform Lambda Tooling Outputs
#
# All outputs are non-sensitive (URLs are IAM-auth-gated; not credentials).
# They print on `terraform output` once T2.1 applies the platform surface.
# ============================================================================

output "platform_lambda_function_urls" {
  description = "Map of platform Lambda name to function URL"
  sensitive   = false
  value = {
    log_rec      = aws_lambda_function_url.log_rec.function_url
    log_decision = aws_lambda_function_url.log_decision.function_url
    query        = aws_lambda_function_url.query.function_url
    update_rec   = aws_lambda_function_url.update_rec.function_url
    list_tools   = aws_lambda_function_url.list_tools.function_url
    maintenance  = aws_lambda_function_url.maintenance.function_url
  }
}

output "platform_lambda_arns" {
  description = "Map of platform Lambda name to function ARN"
  sensitive   = false
  value = {
    log_rec      = aws_lambda_function.log_rec.arn
    log_decision = aws_lambda_function.log_decision.arn
    query        = aws_lambda_function.query.arn
    update_rec   = aws_lambda_function.update_rec.arn
    list_tools   = aws_lambda_function.list_tools.arn
    maintenance  = aws_lambda_function.maintenance.arn
  }
}

output "platform_dev_role_arn" {
  description = "ARN of the PlatformDev IAM role (Pattern B agent-auth, replaces SSO permission set)"
  sensitive   = false
  value       = aws_iam_role.platform_dev.arn
}

output "platform_admin_role_arn" {
  description = "ARN of the PlatformAdmin IAM role (Pattern B agent-auth, replaces SSO permission set)"
  sensitive   = false
  value       = aws_iam_role.platform_admin.arn
}

output "platform_account_id" {
  description = "Personal AWS account id hosting the platform Lambda surface"
  sensitive   = false
  value       = var.platform_account_id
}

output "platform_profile_name" {
  description = "AWS SSO profile name for the personal platform account"
  sensitive   = false
  value       = var.platform_profile_name
}
