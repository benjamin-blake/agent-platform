# DuckLake operational lakehouse -- RDS PostgreSQL catalog (T2.16 / CD.31 / Decision 78).
#
# This is a Glue-analog metadata store, NOT a query engine. DuckDB performs all computation against
# S3 Parquet data; the RDS catalog only holds DuckLake metadata (table/version/snapshot pointers).
# Lambda runtime (T2.17), maintenance pipeline (T2.18), and the ops write/read migration (T2.19)
# consume the outputs of this module.
#
# NETWORK POSTURE (foundation step, intentionally minimal):
#   Default VPC + publicly_accessible = true, with the security group locked to an explicit CIDR
#   allow-list (var.ducklake_catalog_ingress_cidrs). This makes the ATTACH round-trip runnable from
#   local DuckDB under the Decision-67 Lambda freeze. T2.17 re-homes the catalog into a dedicated,
#   private, VPC-attached, controlled-egress posture and flips publicly_accessible to false.
#
# CREDENTIAL POSTURE:
#   manage_master_user_password = true -- RDS owns the secret in Secrets Manager; no password literal
#   in Terraform state. IAM database auth is deliberately NOT used here: it would add aws_iam_*
#   resources (blocking the Decision-77 sandbox auto-apply guard from auto-applying create-only DB
#   changes) and add 15-minute token-refresh plumbing to every DuckDB ATTACH. Decision 36's
#   no-IAM-users posture was work-account-only and is not binding in this module (terraform/CLAUDE.md).
#
# APPLY POSTURE:
#   The first paid-RDS apply is a deliberate manual `agent_platform_admin` apply from the branch,
#   BEFORE merge (Decision 35). DO NOT rely on the Decision-77 sandbox auto-apply -- the guard's
#   IAM_SENSITIVE_TYPES covers only aws_iam_* + trust + destroy/replace, so a create-only
#   aws_db_instance + aws_security_group + (RDS-managed) secret returns guard exit 0. Applying
#   manually first updates the shared S3 state so any post-merge CD plan is a no-op.

# ---------------------------------------------------------------------------
# Network discovery -- default VPC + subnets.
#
# T2.16 uses the default VPC; T2.17 stands up a dedicated VPC and re-points these data sources.
# ---------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ---------------------------------------------------------------------------
# DB subnet group.
#
# RDS requires subnets in at least two AZs even for single-AZ instances (the second AZ is the
# failover target if multi_az is ever flipped on). The default VPC's subnets span all AZs in the
# region, so data.aws_subnets.default satisfies this.
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "ducklake_catalog" {
  name        = "ducklake-catalog"
  description = "DuckLake catalog (T2.16) -- default VPC subnets; T2.17 re-homes into a dedicated VPC."
  subnet_ids  = data.aws_subnets.default.ids

  tags = {
    Name    = "DuckLake Catalog Subnet Group"
    Purpose = "DuckLake catalog T2.16"
  }
}

# ---------------------------------------------------------------------------
# Security group.
#
# Ingress: 5432 from var.ducklake_catalog_ingress_cidrs (no 0.0.0.0/0 -- variable validation
# rejects it). Egress: unrestricted (the catalog initiates no outbound traffic by design, but RDS
# managed services -- patching, snapshots -- need AWS-internal reachability).
# ---------------------------------------------------------------------------

resource "aws_security_group" "ducklake_catalog" {
  name        = "ducklake-catalog"
  description = "DuckLake catalog (T2.16) -- 5432 from an explicit CIDR allow-list."
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name    = "DuckLake Catalog SG"
    Purpose = "DuckLake catalog T2.16 ingress allow-list"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ducklake_catalog_pg" {
  for_each = toset(var.ducklake_catalog_ingress_cidrs)

  security_group_id = aws_security_group.ducklake_catalog.id
  description       = "PostgreSQL from DuckLake catalog allow-list"
  cidr_ipv4         = each.value
  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"

  tags = {
    Name    = "DuckLake Catalog Ingress ${each.value}"
    Purpose = "DuckLake catalog T2.16 PostgreSQL ingress"
  }
}

resource "aws_vpc_security_group_egress_rule" "ducklake_catalog_all" {
  security_group_id = aws_security_group.ducklake_catalog.id
  description       = "All egress (RDS-managed patching, snapshots)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"

  tags = {
    Name    = "DuckLake Catalog Egress"
    Purpose = "DuckLake catalog T2.16 egress"
  }
}

# ---------------------------------------------------------------------------
# DB parameter group -- enforce TLS for all client connections.
#
# rds.force_ssl is a DYNAMIC parameter (no instance reboot required to take effect). Without it,
# RDS accepts plaintext PostgreSQL connections by default; with publicly_accessible = true that
# would mean plaintext credentials on the open internet from any IP in the SG allow-list. The
# DuckDB ATTACH connection helper must set sslmode=require to match.
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "ducklake_catalog_force_ssl" {
  name        = "ducklake-catalog-pg16"
  family      = "postgres16"
  description = "DuckLake catalog T2.16 -- force TLS for all client connections."

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }

  tags = {
    Name    = "DuckLake Catalog Parameter Group"
    Purpose = "DuckLake catalog T2.16 force TLS"
  }
}

# ---------------------------------------------------------------------------
# RDS PostgreSQL instance -- the DuckLake catalog backend.
#
# engine_version = "16" lets AWS select the current default minor at create time; the apply
# subsequently sees no drift because auto_minor_version_upgrade keeps the running minor patched
# inside the same major. Pinning a minor would force regular re-pin work for no reproducibility win.
#
# manage_master_user_password = true -- RDS creates + rotates the Secrets Manager secret. The
# secret ARN is exposed as master_user_secret[0].secret_arn (a computed list block introduced in
# AWS provider 5.x).
#
# deletion_protection = true forces an explicit two-step destroy: flip deletion_protection off via
# terraform, THEN terraform destroy. skip_final_snapshot = false (the safer default for a
# stateful catalog -- this is the Glue-analog metadata pointer back to all S3 Parquet data per
# Decision 78) requires a final_snapshot_identifier; the standard fixed name keeps the destroy
# lifecycle deterministic. T2.17/T2.19 will revisit and may flip skip_final_snapshot dynamics for
# the migration-cutover instance.
# ---------------------------------------------------------------------------

resource "aws_db_instance" "ducklake_catalog" {
  identifier     = "ducklake-catalog"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.ducklake_catalog_instance_class

  db_name  = var.ducklake_catalog_db_name
  username = "ducklake_admin"

  # RDS-managed master secret in Secrets Manager. No password literal in TF state.
  manage_master_user_password = true

  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az               = false # single-AZ per Decision 78 / T2.16 baseline
  publicly_accessible    = true  # T2.17 flips to false after VPC re-home
  db_subnet_group_name   = aws_db_subnet_group.ducklake_catalog.name
  vpc_security_group_ids = [aws_security_group.ducklake_catalog.id]

  port = 5432

  parameter_group_name = aws_db_parameter_group.ducklake_catalog_force_ssl.name

  backup_retention_period    = 7                     # PITR window (Decision 78 / T2.16 acceptance), UTC schedule below
  backup_window              = "02:00-03:00"         # UTC
  maintenance_window         = "sun:03:30-sun:04:30" # UTC
  copy_tags_to_snapshot      = true
  auto_minor_version_upgrade = true

  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "ducklake-catalog-final-snapshot"
  delete_automated_backups  = true

  performance_insights_enabled = false # paid feature; default-off in sandbox

  tags = {
    Name    = "DuckLake Catalog"
    Purpose = "DuckLake v1.0 ops/telemetry catalog backend T2.16 CD.31"
  }
}

# ---------------------------------------------------------------------------
# Outputs -- consumed by T2.17 (Lambda runtime) and the VP-6 ATTACH round-trip.
# ---------------------------------------------------------------------------

output "ducklake_catalog_endpoint" {
  description = "DuckLake catalog connection endpoint in host:port form. DuckDB ATTACH consumes host + port separately."
  value       = aws_db_instance.ducklake_catalog.endpoint
}

output "ducklake_catalog_address" {
  description = "DuckLake catalog hostname (no port)."
  value       = aws_db_instance.ducklake_catalog.address
}

output "ducklake_catalog_port" {
  description = "DuckLake catalog TCP port (always 5432)."
  value       = aws_db_instance.ducklake_catalog.port
}

output "ducklake_catalog_db_name" {
  description = "Initial PostgreSQL database name created at launch. DuckLake metadata schemas live within this database."
  value       = aws_db_instance.ducklake_catalog.db_name
}

output "ducklake_catalog_master_secret_arn" {
  description = "RDS-managed master-user secret ARN (Secrets Manager). Consumed by T2.17 Lambda runtime and the VP-6 ATTACH round-trip."
  value       = aws_db_instance.ducklake_catalog.master_user_secret[0].secret_arn
}
