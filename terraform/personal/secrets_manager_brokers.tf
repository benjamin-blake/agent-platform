# T2.14 -- Alpaca broker credential envelopes (paper + live).
#
# Secret VALUES are set out-of-band via aws secretsmanager put-secret-value -- never Terraform-managed.
# No secret-version resources: key material must never enter Terraform state (Decision 37 out-of-band
# precedent; mirrors inference_credentials.tf). The ARNs are exported as outputs and referenced by
# the BrokerCredentialsRead IAM statement in platform_roles.tf, ensuring the grant is ARN-scoped (no wildcard).
#
# APPLY POSTURE (Decision 77 + Decision 35):
# aws_secretsmanager_secret creates are NOT in the guard's IAM_SENSITIVE_TYPES and would normally
# auto-apply. However, the BrokerCredentialsRead statement added to platform_roles.tf IS an IAM
# change and fail-closes the guard (guard exit 2), so the ENTIRE plan (secrets + IAM) lands via
# agent_platform_admin (PlatformAdmin) interactive apply: terraform plan -> present -> accept -> apply.
# IAM apply precedes any runtime credential read (IAM-precedence rule).
#
# Tag values: ASCII-tag-charset only (letters/digits/spaces and + - = . _ : / @). The AWS Secrets
# Manager tagging service rejects parentheses, so tier references are written "T2.14", not "(T2.14)"
# (the latter fails TagResource with InvalidRequestException and blocks every module apply).
# Mirrors the inference_credentials.tf precedent verbatim.

resource "aws_secretsmanager_secret" "alpaca_paper" {
  name        = "agent-platform-broker-alpaca-paper" # pragma: allowlist secret -- public Secrets Manager resource name, not a value
  description = "Alpaca paper-trading API key set, paper-api.alpaca.markets -- T2.14 broker credential routing. ROTATION: quarterly, calendar-reminded (T2.5 cross-secret rotation policy; user_action_required). Value set out-of-band via put-secret-value; never Terraform-managed (Decision 37). Consumers: L3.exec.3 PaperBroker, L3.exec.4 AlpacaBroker."

  tags = {
    Name    = "Alpaca Paper Broker Key"
    Purpose = "T2.14 broker credential routing - paper account alpaca paper-api.alpaca.markets"
  }
}

resource "aws_secretsmanager_secret" "alpaca_live" {
  name        = "agent-platform-broker-alpaca-live" # pragma: allowlist secret -- public Secrets Manager resource name, not a value
  description = "Alpaca live-trading API key set, api.alpaca.markets -- T2.14 broker credential routing. ROTATION: quarterly, calendar-reminded (T2.5 cross-secret rotation policy; user_action_required). Value set out-of-band; never Terraform-managed (Decision 37). Realized at product live_small. Consumer: L3.exec.4 AlpacaBroker."

  tags = {
    Name    = "Alpaca Live Broker Key"
    Purpose = "T2.14 broker credential routing - live account alpaca api.alpaca.markets"
  }
}

output "alpaca_paper_secret_arn" {
  description = "Secrets Manager ARN of the Alpaca paper-trading API key envelope. Runtime-fetched via scripts/broker_secrets.py resolve (Decision 37 / T2.14 credential-routing contract)."
  value       = aws_secretsmanager_secret.alpaca_paper.arn
}

output "alpaca_live_secret_arn" {
  description = "Secrets Manager ARN of the Alpaca live-trading API key envelope. Runtime-fetched via scripts/broker_secrets.py resolve (Decision 37 / T2.14 credential-routing contract). Realized at product live_small."
  value       = aws_secretsmanager_secret.alpaca_live.arn
}
