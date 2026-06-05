# DuckLake operational lakehouse -- Neon serverless Postgres catalog (T2.16b / CD.34, pending).
#
# Replaces the T2.16 RDS catalog (rds_ducklake_catalog.tf, retired in Phase 2) with Neon serverless
# Postgres on the free tier ($0). Like RDS, this is a Glue-analog metadata store, NOT a query engine:
# DuckDB performs all computation against S3 Parquet; the catalog holds only DuckLake metadata
# (table/version/snapshot pointers). Nothing consumes the catalog yet (live ops are Iceberg/Athena
# until the T2.19 cutover), so present blast radius is zero.
#
# ---------------------------------------------------------------------------
# APPLY POSTURE (Decision 77 + the 2026-06-04 posture pivot)
# ---------------------------------------------------------------------------
# These Neon resources + the DSN secret AUTO-APPLY via the sandbox pipeline behind the Neon-aware
# fail-closed guard (scripts/terraform_apply_guard.py) + subagent review -- they are NOT carved out of
# Decision-77. The guard blocks any neon_* update / replace / delete (the mutation surface where
# allow-list widening, credential rotation, or project deletion would happen) and ALLOWS a neon_*
# create. A create is safe on the strength of compensating controls, NOT an IP allow-list: enforced
# TLS (sslmode=require), a scoped non-owner neon_role, and the DSN held in Secrets Manager. Neon
# IP-Allow is a Scale-plan feature (unavailable on the free tier) and egress here is dynamic (CC-web
# containers + GitHub-hosted runners + Lambda), so no static allow-list is set (REPORT R3 / CD.34).
#
# aws_secretsmanager_secret is NOT in the guard's IAM_SENSITIVE_TYPES, so the DSN-secret create also
# returns guard exit 0 and auto-applies.
#
# ---------------------------------------------------------------------------
# PHASE 0 PREREQUISITES (one-time, manual from the admin container, BEFORE Phase 1 merges)
# ---------------------------------------------------------------------------
#   1. Create the Neon provider API key secret out-of-band (plaintext; human-run; NOT Terraform-managed
#      -- Terraform-managing the key the provider reads would create a provider->resource cycle):
#        aws secretsmanager create-secret --name neon-api-key \
#          --secret-string '<neon-api-key>' --region eu-west-2 --profile agent_platform_admin
#   2. Grant the CI apply role secretsmanager rights on the two secret ARNs (oidc.tf,
#      aws_iam_role_policy.github_ci_apply) and apply JUST that statement manually (IAM-sensitive ->
#      the guard fail-closes, so it cannot auto-apply):
#        terraform apply -target=aws_iam_role_policy.github_ci_apply   # from the admin container
# After Phase 0, Phase 1 auto-applies cleanly: the neon-api-key secret + the apply-role grant already
# exist (the provider data source resolves at plan time), and the Neon creates + DSN-secret create
# return guard exit 0.

# The neon provider is pinned in main.tf's required_providers block (Terraform allows only one such
# block per module). Its checksums are committed in .terraform.lock.hcl (supply-chain control).
#
# Neon provider API key, read from the out-of-band Secrets Manager secret (Phase 0). This data source
# resolves at plan time; it is NOT a Terraform-managed resource (no provider->resource cycle).
data "aws_secretsmanager_secret_version" "neon_api_key" {
  secret_id = "neon-api-key"
}

provider "neon" {
  api_key = data.aws_secretsmanager_secret_version.neon_api_key.secret_string
}

# ---------------------------------------------------------------------------
# Neon project -- the catalog. Free tier: 0.5 GB storage, 100 CU-hours/mo, scale-to-zero. pg_version
# 16 matches the prior RDS engine. org_id is required by Neon's org-based model (every account, incl.
# personal, has a default organization) -- it is an identifier, not a secret. No allowed_ips (free-tier
# posture -- see APPLY POSTURE above). The project auto-creates a default branch + endpoint; the scoped
# role and the catalog database below live on that default branch.
# ---------------------------------------------------------------------------

resource "neon_project" "ducklake_catalog" {
  name       = "ducklake-catalog"
  org_id     = var.neon_org_id
  region_id  = var.neon_region_id
  pg_version = 16

  # Free-plan PITR ceiling is 21600s (6h); the provider's 24h (86400) default is rejected on free.
  # This is the ~6h free-tier history window the DR design accounts for (daily pg_dump covers >6h).
  history_retention_seconds = 21600
}

# Scoped, non-owner role for catalog access. Distinct from the project's auto-created owner role so the
# DuckLake runtime credential is least-privilege (REPORT R3 compensating control).
resource "neon_role" "ducklake_ops" {
  project_id = neon_project.ducklake_catalog.id
  branch_id  = neon_project.ducklake_catalog.default_branch_id
  name       = "ducklake_ops"
}

# Catalog database. The DuckLake metadata schema (META_SCHEMA 'ducklake_ops', created post-provision
# from migrations/ducklake_ops_schema.sql) lives WITHIN this database.
resource "neon_database" "ducklake_ops" {
  project_id = neon_project.ducklake_catalog.id
  branch_id  = neon_project.ducklake_catalog.default_branch_id
  name       = "ducklake_ops"
  owner_name = neon_role.ducklake_ops.name
}

# ---------------------------------------------------------------------------
# Assembled DSN for the catalog, stored in Secrets Manager (Decision 37 runtime-fetch precedent).
# Uses the DIRECT (unpooled) endpoint host -- DuckLake commits are multi-statement transactions, which
# PgBouncer transaction-mode pooling can break (the pooled endpoint is host_pooler; used only if proven
# transaction-safe, per the T2.16b connection-churn gate). TLS enforced via sslmode=require.
#
# ROTATION: the Neon role password does NOT auto-rotate like the prior RDS-managed master secret
# (manage_master_user_password). Rotate quarterly, calendar-reminded (repo convention; recorded in the
# secret description).
# ---------------------------------------------------------------------------

locals {
  ducklake_neon_dsn = format(
    "postgresql://%s:%s@%s/%s?sslmode=require", # pragma: allowlist secret -- format template, not a literal credential
    neon_role.ducklake_ops.name,
    neon_role.ducklake_ops.password,
    neon_project.ducklake_catalog.database_host,
    neon_database.ducklake_ops.name,
  )
}

resource "aws_secretsmanager_secret" "ducklake_neon_catalog_dsn" {
  name        = "ducklake-neon-catalog-dsn"
  description = "DuckLake Neon catalog DSN (direct endpoint, sslmode=require). ROTATION: quarterly, calendar-reminded -- the Neon role password does not auto-rotate (CD.34 / Decision 37)."

  tags = {
    Name    = "DuckLake Neon Catalog DSN"
    Purpose = "DuckLake catalog T2.16b CD.34 -- Lambda/smoke-test runtime-fetch"
  }
}

resource "aws_secretsmanager_secret_version" "ducklake_neon_catalog_dsn" {
  secret_id = aws_secretsmanager_secret.ducklake_neon_catalog_dsn.id
  secret_string = jsonencode({
    dsn         = local.ducklake_neon_dsn
    host        = neon_project.ducklake_catalog.database_host
    dbname      = neon_database.ducklake_ops.name
    username    = neon_role.ducklake_ops.name
    password    = neon_role.ducklake_ops.password
    sslmode     = "require"
    meta_schema = "ducklake_ops"
  })
}

# ---------------------------------------------------------------------------
# Outputs -- consumed by the T2.16b smoke test + the T2.17 Lambda runtime.
# ---------------------------------------------------------------------------

output "ducklake_neon_catalog_dsn_secret_arn" {
  description = "Secrets Manager ARN of the DuckLake Neon catalog DSN JSON. Runtime-fetched (Decision 37) by the smoke test + the T2.17 Lambdas."
  value       = aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn
}

output "ducklake_neon_catalog_host_direct" {
  description = "Neon DIRECT (unpooled) endpoint host for the DuckLake catalog. Catalog writes use this host (multi-statement DuckLake txns vs transaction-mode pooling)."
  value       = neon_project.ducklake_catalog.database_host
}
