# CD.28 T0.4 -- Tier 1 (DeepSeek) and Tier 2 (Anthropic) inference credential envelopes.
#
# Secret VALUES are set out-of-band via aws secretsmanager put-secret-value -- never Terraform-managed.
# No secret-version resources: key material must never enter Terraform state (Decision 37 out-of-band
# precedent). The neon_ducklake_catalog.tf DSN is the in-band counter-example; these API keys differ --
# they are entered by the human via CLI and must never appear in state.
#
# Both ARNs are exported as outputs and referenced by the InferenceCredentialsRead IAM statement
# in platform_roles.tf, ensuring the grant is ARN-scoped (no wildcard).
#
# APPLY POSTURE (Decision 77 + terraform/CLAUDE.md):
# The aws_secretsmanager_secret creates are NOT in the guard's IAM_SENSITIVE_TYPES and would normally
# auto-apply. However, the InferenceCredentialsRead statement added to platform_roles.tf IS an IAM
# change and fail-closes the guard, so the ENTIRE plan (secrets + IAM) goes through the
# interactive human-gated plan -> present -> accept -> apply loop. IAM apply precedes any runtime
# use of the credentials (IAM-precedence rule).

resource "aws_secretsmanager_secret" "deepseek_api_key" {
  name        = "agent-platform-deepseek-api-key"
  description = "DeepSeek API key -- Tier 1 executor inference (CD.28 / T0.4). ROTATION: quarterly, calendar-reminded (T2.5 cross-secret rotation policy; user_action_required). Value set out-of-band via put-secret-value; never Terraform-managed (Decision 37)."

  tags = {
    Name    = "DeepSeek API Key"
    Purpose = "CD.28 Tier 1 inference - LiteLLM deepseek/deepseek-chat (T0.4)"
  }
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name        = "agent-platform-anthropic-api-key"
  description = "Anthropic API key -- Tier 2 executor inference escape hatch (CD.28 / T0.4). ROTATION: quarterly, calendar-reminded (T2.5 cross-secret rotation policy; user_action_required). Funded by Claude Code Max x5 programmatic-pool (~$100/month). Value set out-of-band; never Terraform-managed (Decision 37)."

  tags = {
    Name    = "Anthropic API Key"
    Purpose = "CD.28 Tier 2 inference - LiteLLM anthropic/claude-haiku-4-5 (T0.4)"
  }
}

output "deepseek_api_key_secret_arn" {
  description = "Secrets Manager ARN of the DeepSeek API key envelope. Runtime-fetched (Decision 37) by the smoke-test and the future T4.2 LiteLLM transport."
  value       = aws_secretsmanager_secret.deepseek_api_key.arn
}

output "anthropic_api_key_secret_arn" {
  description = "Secrets Manager ARN of the Anthropic API key envelope. Runtime-fetched (Decision 37) by the smoke-test and the future T4.2 LiteLLM transport."
  value       = aws_secretsmanager_secret.anthropic_api_key.arn
}
