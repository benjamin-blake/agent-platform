# Personal-account platform infrastructure (isolated root module) -- PLAN-public-migration Phase B.
#
# WHY a separate root module: the work-account root (terraform/) points its DEFAULT aws provider
# at the work account and only ~8 of ~137 resources use the aws.platform alias. Applying that root
# against the personal account would try to CREATE ~120 work-account resources. This module holds
# ALL personal-account infra with its OWN provider + state and is the ONLY root applied post-CD.21.
#
# Provisioning profile is agent_platform_admin (PlatformAdmin) -- creates IAM + OIDC, which the
# permissionless agent_platform (PlatformDev) runtime role cannot. Runtime stays agent_platform.
# The account ID is supplied at apply time via the gitignored terraform.personal.tfvars; it is
# never a committed literal (PLAN Step 11b parameterisation invariant).

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  # Local backend bootstraps the data-lake bucket; an S3 backend cannot be used before the bucket
  # it would live in exists. State + .terraform/ are gitignored (terraform/**/ patterns).
  backend "local" {}
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = "agent-platform"
      Account   = "personal"
      ManagedBy = "Terraform"
      Owner     = var.owner_email
    }
  }
}

# ---------------------------------------------------------------------------
# Glue catalog database + Athena production workgroup
# ---------------------------------------------------------------------------

resource "aws_glue_catalog_database" "ops" {
  name        = "agent_platform"
  description = "Personal-account operational data lake (ops_recommendations / ops_decisions / ops_priority_queue Iceberg tables)"
}

resource "aws_athena_workgroup" "production" {
  name        = "agent-platform-production"
  description = "Production queries: OPTIMIZE, MERGE writes, all ops portal/preflight queries"

  # A rename forces destroy-then-create; DeleteWorkGroup rejects a workgroup that holds
  # query-execution history unless RecursiveDeleteOption is set. force_destroy maps to it.
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data_lake.id}/athena/prod-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }

  tags = {
    Name = "Production Workgroup"
  }
}

# ---------------------------------------------------------------------------
# Data-lake S3 bucket (Iceberg table storage + Athena results)
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "data_lake" {
  bucket = "agent-platform-data-lake"

  tags = {
    Name    = "Platform Data Lake"
    Purpose = "Iceberg ops tables + Athena query results"
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "data_lake_https_only" {
  bucket = aws_s3_bucket.data_lake.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyNonHTTPS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# DynamoDB atomic counters (rec/decision ID allocation, Decision 36/37: SSO, no IAM users)
# Seeded create-only ABOVE the work-account max + 1000 margin (Decision 50 collision guard).
# Work maxes read 2026-05-28: recommendations=944, decisions=81. Seed floor = max + 1000.
# Migration Step 13c re-asserts counter >= max(migrated_id) + margin monotonically afterwards.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "counters" {
  name         = "agent-platform-counters"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "counter_name"

  attribute {
    name = "counter_name"
    type = "S"
  }

  tags = {
    Purpose = "Atomic sequential counter allocation for agents and executor"
  }
}

resource "aws_dynamodb_table_item" "seed_recommendations" {
  table_name = aws_dynamodb_table.counters.name
  hash_key   = aws_dynamodb_table.counters.hash_key

  item = jsonencode({
    counter_name  = { S = "recommendations" }
    current_value = { N = "1944" }
  })

  # Create-only: never lower an existing counter (the migration may raise it monotonically).
  lifecycle {
    ignore_changes = [item]
  }
}

resource "aws_dynamodb_table_item" "seed_decisions" {
  table_name = aws_dynamodb_table.counters.name
  hash_key   = aws_dynamodb_table.counters.hash_key

  item = jsonencode({
    counter_name  = { S = "decisions" }
    current_value = { N = "1081" }
  })

  lifecycle {
    ignore_changes = [item]
  }
}

# ---------------------------------------------------------------------------
# Iceberg ops tables + _current views.
#
# Created via Athena DDL (null_resource + local-exec) rather than aws_glue_catalog_table, because
# Iceberg requires Athena to own the table metadata location -- the same proven pattern used by the
# work-account terraform/iceberg_tables.tf. Schemas mirror the work tables verbatim. Views are
# created explicitly here (NOT lazily on first portal write) because the migration idempotency guard
# and read_priority_queue() (Decision 61) query the _current views on a greenfield account before any
# write; the views must already exist (returning 0 rows).
# ---------------------------------------------------------------------------

locals {
  ops_location_prefix = "s3://${aws_s3_bucket.data_lake.bucket}/iceberg"

  create_ops_table_queries = {
    ops_recommendations = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.ops.name}.ops_recommendations (
        id string COMMENT 'Recommendation ID (e.g., rec-001)',
        title string COMMENT 'Concise description',
        source string COMMENT 'Origin: executor-supervision, code-review, planning, brainstorm',
        effort string COMMENT 'XS, S, M, L, or XL',
        priority string COMMENT 'Critical, High, Medium, or Low',
        status string COMMENT 'open, closed, failed, declined, or superseded',
        automatable boolean COMMENT 'Whether the executor can handle this',
        risk string COMMENT 'low, medium, or high',
        file string COMMENT 'Primary target file path',
        context string COMMENT 'Why this rec exists',
        acceptance string COMMENT 'Shell command returning 0 on success',
        dependencies array<string> COMMENT 'Blocking rec IDs',
        tags array<string> COMMENT 'Categorisation tags',
        resolution string COMMENT 'Why declined or superseded',
        execution_result string COMMENT 'success, failure, manual, or already_implemented',
        execution_date string COMMENT 'ISO-8601 timestamp set by executor',
        execution_branch string COMMENT 'Branch name set by executor',
        execution_pr_url string COMMENT 'PR URL set by executor',
        execution_steps int COMMENT 'Step count set by executor',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.ops_location_prefix}/ops_recommendations/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ops_decisions = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.ops.name}.ops_decisions (
        id string COMMENT 'Canonical string key (dec-NNN). Introduced Phase 0+1.',
        decision_id int COMMENT 'Sequential decision number (e.g., 50)',
        title string COMMENT 'Decision title',
        status string COMMENT 'Decided, Superseded, or Open',
        problem string COMMENT 'Problem statement',
        decision_text string COMMENT 'The decision made',
        context string COMMENT 'Why this decision was made',
        decided_date string COMMENT 'ISO date decided',
        related_decisions array<int> COMMENT 'Related decision IDs (legacy; deprecated in Phase 6)',
        related_decisions_v2 array<string> COMMENT 'Related decision IDs in dec-NNN format (introduced Phase 0+1)',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.ops_location_prefix}/ops_decisions/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ops_priority_queue = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.ops.name}.ops_priority_queue (
        queue_run_id string COMMENT 'UUID shared by all entries in one curator run',
        rank int COMMENT 'Priority rank within the run (1 = highest)',
        rec_id string COMMENT 'Recommendation ID',
        mode string COMMENT 'solo or compound',
        compound_with array<string> COMMENT 'Other rec IDs in compound run',
        rationale string COMMENT 'Why this rec is ranked here',
        gates array<string> COMMENT 'Blocking gate conditions',
        north_star_impact string COMMENT 'How this serves the North Star',
        decay_date string COMMENT 'Date after which this entry is stale',
        status string COMMENT 'queued, executing, or done',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.ops_location_prefix}/ops_priority_queue/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT
  }

  create_ops_view_queries = {
    ops_recommendations_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.ops.name}.ops_recommendations_current AS
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num
        FROM ${aws_glue_catalog_database.ops.name}.ops_recommendations
      )
      WHERE row_num = 1
    EOT

    ops_decisions_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.ops.name}.ops_decisions_current AS
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num
        FROM ${aws_glue_catalog_database.ops.name}.ops_decisions
      )
      WHERE row_num = 1
    EOT

    ops_priority_queue_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.ops.name}.ops_priority_queue_current AS
      SELECT * FROM ${aws_glue_catalog_database.ops.name}.ops_priority_queue
      WHERE queue_run_id = (
        SELECT queue_run_id
        FROM ${aws_glue_catalog_database.ops.name}.ops_priority_queue
        ORDER BY last_updated_timestamp DESC
        LIMIT 1
      )
    EOT
  }
}

resource "null_resource" "create_ops_tables" {
  for_each = local.create_ops_table_queries

  triggers = {
    query_hash = md5(each.value)
  }

  provisioner "local-exec" {
    command     = <<-EOT
      $QueryFile = [System.IO.Path]::GetTempFileName()
      $Query = @'
${each.value}
'@
      $Query | Out-File -FilePath $QueryFile -Encoding utf8

      $QueryId = aws athena start-query-execution `
        --query-string (Get-Content $QueryFile -Raw) `
        --query-execution-context Database=${aws_glue_catalog_database.ops.name} `
        --work-group ${aws_athena_workgroup.production.name} `
        --region ${var.aws_region} `
        --profile ${var.aws_profile} `
        --query 'QueryExecutionId' `
        --output text

      if ($LASTEXITCODE -ne 0) {
        Remove-Item $QueryFile
        exit 1
      }

      do {
        Start-Sleep -Seconds 2
        $Status = aws athena get-query-execution `
          --query-execution-id $QueryId `
          --region ${var.aws_region} `
          --profile ${var.aws_profile} `
          --query 'QueryExecution.Status.State' `
          --output text
      } while ($Status -eq 'RUNNING' -or $Status -eq 'QUEUED')

      Remove-Item $QueryFile

      if ($Status -ne 'SUCCEEDED') {
        Write-Error "Athena table creation failed with status: $Status"
        exit 1
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
    # CREATE TABLE IF NOT EXISTS returns FAILED (not SUCCEEDED) when the table already exists --
    # expected idempotent behaviour on re-apply. Does NOT mask real failures; recheck Athena history
    # if a table is missing. Mirrors terraform/iceberg_tables.tf.
    on_failure = continue
  }

  depends_on = [
    aws_glue_catalog_database.ops,
    aws_athena_workgroup.production,
    aws_s3_bucket.data_lake
  ]
}

resource "null_resource" "create_ops_views" {
  for_each = local.create_ops_view_queries

  triggers = {
    query_hash = md5(each.value)
  }

  provisioner "local-exec" {
    command     = <<-EOT
      $QueryFile = [System.IO.Path]::GetTempFileName()
      $Query = @'
${each.value}
'@
      $Query | Out-File -FilePath $QueryFile -Encoding utf8

      $QueryId = aws athena start-query-execution `
        --query-string (Get-Content $QueryFile -Raw) `
        --query-execution-context Database=${aws_glue_catalog_database.ops.name} `
        --work-group ${aws_athena_workgroup.production.name} `
        --region ${var.aws_region} `
        --profile ${var.aws_profile} `
        --query 'QueryExecutionId' `
        --output text

      if ($LASTEXITCODE -ne 0) {
        Remove-Item $QueryFile
        exit 1
      }

      do {
        Start-Sleep -Seconds 2
        $Status = aws athena get-query-execution `
          --query-execution-id $QueryId `
          --region ${var.aws_region} `
          --profile ${var.aws_profile} `
          --query 'QueryExecution.Status.State' `
          --output text
      } while ($Status -eq 'RUNNING' -or $Status -eq 'QUEUED')

      Remove-Item $QueryFile

      if ($Status -ne 'SUCCEEDED') {
        Write-Error "Athena view creation failed with status: $Status"
        exit 1
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
    on_failure  = continue
  }

  depends_on = [null_resource.create_ops_tables]
}
