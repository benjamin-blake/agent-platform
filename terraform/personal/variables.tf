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

# ---------------------------------------------------------------------------
# DuckLake catalog (T2.16) -- RDS PostgreSQL backend for the DuckLake v1.0
# operational lakehouse (Decision 78 / CD.31). Ingress CIDRs are an explicit
# allow-list with NO default; supplied via gitignored terraform.personal.tfvars.
# ---------------------------------------------------------------------------

variable "ducklake_catalog_ingress_cidrs" {
  description = <<-EOT
    Allow-list of CIDR blocks permitted to reach the DuckLake RDS catalog on 5432. Must NEVER include 0.0.0.0/0.

    TEMPORARY DEFAULT (T2.16b / CD.34, Phase 1): the sandbox auto-apply workflow injects only 4 TF_VAR_* and
    does not pull the gitignored tfvars, so a no-default value reds `terraform plan` in CI and blocks ALL
    sandbox applies (the state on 2026-06-03 after the RDS merge). The default below EQUALS the currently
    deployed value (pulled from state) so the RDS plans as a no-op -- a divergent value would show
    ingress-rule deletes, which the Decision-77 guard fail-closes on. This whole variable is removed in
    Phase 2 together with rds_ducklake_catalog.tf.
  EOT
  type        = list(string)
  default     = ["20.0.202.217/32"]

  validation {
    condition     = length(var.ducklake_catalog_ingress_cidrs) > 0
    error_message = "ducklake_catalog_ingress_cidrs must be a non-empty allow-list."
  }

  validation {
    condition     = !contains(var.ducklake_catalog_ingress_cidrs, "0.0.0.0/0")
    error_message = "ducklake_catalog_ingress_cidrs must NOT include 0.0.0.0/0 -- supply an explicit egress CIDR."
  }
}

variable "ducklake_catalog_db_name" {
  description = "Initial PostgreSQL database name created at instance launch. The DuckLake metadata schema (e.g. ducklake_ops) lives WITHIN this database -- one RDS instance can host multiple DuckLake catalogs by schema (OQ.14 separability)."
  type        = string
  default     = "ducklake_catalog"
}

variable "ducklake_catalog_instance_class" {
  description = "RDS instance class for the DuckLake catalog. db.t4g.micro is the Decision-78 baseline (burstable ARM, ~$12/mo single-AZ)."
  type        = string
  default     = "db.t4g.micro"
}

# ---------------------------------------------------------------------------
# DuckLake catalog -- Neon serverless Postgres backend (T2.16b / CD.34, pending).
#
# The Neon provider API key is NOT a variable: the provider reads it from a Secrets Manager secret
# (`neon-api-key`) created out-of-band in Phase 0 (see neon_ducklake_catalog.tf). Making it a var
# would either commit a literal or, if Terraform-managed, create a provider->resource cycle.
#
# There is no neon_org_id: this is a personal Neon account (no organization).
#
# There is no neon_catalog_allowed_ips: Neon IP-Allow is a Scale-plan feature (unavailable on the
# free tier this migration targets) and egress here is dynamic (CC-web + GitHub-hosted runners +
# Lambda), so no static allow-list is maintainable. The free-tier posture rests on compensating
# controls -- enforced TLS (sslmode=require) + a scoped non-owner neon_role + the DSN in Secrets
# Manager -- and the Neon-aware apply guard fail-closes on any neon_* update/replace/delete.
# ---------------------------------------------------------------------------

variable "neon_region_id" {
  description = "Neon region_id for the DuckLake catalog project. Default aws-eu-west-2 (Neon AWS Europe/London) co-locates with the eu-west-2 data lake. Verified against Neon's supported-regions list at implementation time."
  type        = string
  default     = "aws-eu-west-2"
}
