# DuckLake maintenance ADMIN singleton Lambda (T2.18 / CD.33, Decision 81; T2.18 c9 follow-on
# split, bundled Decision amending Decision 81 clause 1, runtime artifacts 3 -> 4).
#
# Admin-gated: retains the production-destructive and operational verbs (catalog_reinit,
# restore_drill, reconcile_columns, catalog_stats, clone_catalog) plus the scheduled merge_ops
# cadence (production ops_* catalog, every 6h, non-destructive). The non-destructive smoke cadences
# (merge/gc/hot_merge/breaker_probe) moved to ducklake_maintenance_smoke.tf's CI-invokable sibling
# function -- see that file for the corresponding EventBridge rules (moved there via `moved {}`
# blocks preserving their AWS name/ARN).
#
# reserved_concurrent_executions = 1: maintenance is a singleton (Decision 81 clause 6).
# NOTE: the writer Lambda (ducklake_lambdas.tf) intentionally does NOT set reserved_concurrency so
# its OCC concurrency model is not artificially constrained (Decision 81 clause 3 + Decision 82).
# The maintenance pipeline IS intentionally a singleton -- it must not run concurrently with itself.
# The reserved_concurrency=1 here is correct and is NOT a keyword-collision with the writer's OCC
# model. This distinction is documented to pre-empt a reviewer flag.
#
# ---------------------------------------------------------------------------
# APPLY POSTURE (Decision 35 + 77): HUMAN-GATED via agent_platform_admin.
# ---------------------------------------------------------------------------
# This file creates a NEW IAM role + inline policy, which trips the Decision-77 deterministic guard
# (scripts/terraform_apply_guard.py, fail-closed on IAM/trust change). Apply routes to the MANUAL
# agent_platform_admin path, NOT push-to-main auto-apply. IAM must precede the code deploy:
#   1. build_lambda --ducklake-only       (upload all zips + layers to S3)
#   2. terraform plan -> human review -> terraform apply via agent_platform_admin
#   3. build_lambda --ducklake-only --deploy  (update the function code pointers from S3)
#
# CODE/INFRA COUPLING (Decision 125, environment-taxonomy.md section 5): RESOLVED. The
# aws_lambda_function resource below now carries a lifecycle block ignoring source_code_hash
# changes, so code-only redeploys no longer surface as a Terraform diff on this apply path. Code
# deploys now go via the governed CD channel (.github/workflows/deploy-ducklake-lambdas.yml, T2.38).
#
# FP-B (2026-06-07): shared SNS topic (sns_alerts.tf) created and wired as the alarm_actions
# target for BOTH this circuit-breaker alarm AND the CD.34 catalog-DR freshness alarm.

locals {
  ducklake_maintenance_function = "agent-platform-ducklake-maintenance"
}

# Singleton concurrency cap (Decision 81 clause 6) = 1: AWS physically refuses a second concurrent
# invocation, so the singleton is enforced by the platform, not just by schedule geometry. This was
# briefly -1 (unreserved) at initial deploy because the account Lambda "Concurrent executions" quota
# (L-B99A9384) sat at the unverified-account floor of 10 and PutFunctionConcurrency cannot drop the
# unreserved pool below 10. AWS support case 178085808000233 raised L-B99A9384 to 1000 (2026-06-08),
# so the reservation is now applied. Kept as a variable so the cap can be lifted again for a quota or
# load test without editing the resource body.
variable "ducklake_maintenance_reserved_concurrency" {
  description = "Reserved concurrency for the maintenance singleton (Decision 81 cl.6). 1 = singleton; -1 = unreserved (only for a quota/load test)."
  type        = number
  default     = 1
}

# ---------------------------------------------------------------------------
# CloudWatch log group (pre-created so the execution-role grant can be scoped to its ARN).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ducklake_maintenance" {
  name              = "/aws/lambda/${local.ducklake_maintenance_function}"
  retention_in_days = 14

  tags = {
    Name    = "DuckLake Maintenance Logs"
    Purpose = "T2.18 ducklake_maintenance singleton"
  }
}

# ---------------------------------------------------------------------------
# Write-scoped execution role: S3 Get/Put/Delete/List on the PRODUCTION prefix ONLY (the smoke
# prefix grant moved to ducklake_maintenance_smoke.tf's own exec role -- this narrowing is the
# other half of the T2.18 c9 blast-radius split), DSN read, DuckLakeMaintenance CloudWatch metrics,
# logs.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ducklake_maintenance" {
  # Decision 144 (T2.48): mandatory broad-but-bounded exec-identity boundary (16/17 roles; PlatformAdmin excluded).
  name                 = "agent-platform-ducklake-maintenance"
  description          = "Maintenance admin singleton: S3 RW+Delete on the production prefix ONLY, Neon DSN read, maintenance metrics"
  permissions_boundary = "arn:aws:iam::${var.account_id}:policy/agent-platform-github-ci-apply-boundary"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "ducklake_maintenance" {
  name = "DuckLakeMaintenanceRuntime"
  role = aws_iam_role.ducklake_maintenance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.ducklake_maintenance.arn}:*"]
      },
      {
        Sid      = "NeonDsnRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn]
      },
      {
        # T2.19: the operational actions write to the PRODUCTION prefix -- catalog_reinit at
        # ducklake/, restore_drill at ducklake/_restore_drill/ (a sub-prefix), merge_ops/
        # reconcile_columns at the caller-supplied production data_path. delete_orphaned_files is
        # catalog-wide but only ever invoked against the production catalog on this function (the
        # smoke cadences that touched the smoke prefix moved to ducklake_maintenance_smoke.tf).
        Sid      = "S3DataReadWriteDelete"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/${local.ducklake_prod_data_prefix}/*"]
      },
      {
        Sid      = "S3ListDataPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.ducklake_prod_data_prefix}/*"]
          }
        }
      },
      {
        # PutMetricData does not support resource-level scoping; constrain to the maintenance namespace.
        Sid      = "CloudWatchMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "DuckLakeMaintenance"
          }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Lambda function (from S3). Layers reused from T2.17 (no new layer build).
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "ducklake_maintenance" {
  function_name = local.ducklake_maintenance_function
  description   = "T2.18 DuckLake maintenance ADMIN singleton (CD.33/Decision 81). Production-destructive + operational verbs; merge_ops every 6h."
  role          = aws_iam_role.ducklake_maintenance.arn
  runtime       = "python3.12"
  handler       = "src.lambdas.ducklake_maintenance.handler.handler"
  architectures = ["x86_64"]
  timeout       = 300
  memory_size   = 1024

  # Singleton cap (Decision 81 clause 6) = 1 via the variable default. Differs from the writer's OCC
  # model (no reserved concurrency, clause 3). See the variable definition above for the quota history.
  reserved_concurrent_executions = var.ducklake_maintenance_reserved_concurrency

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ducklake-maintenance.zip"
  source_code_hash = try(filemd5("${path.module}/../../lambda-packages/ducklake-maintenance.zip"), null)

  layers = [
    aws_lambda_layer_version.ducklake_deps.arn,
    aws_lambda_layer_version.ducklake_extensions.arn,
    # T2.19: restore_drill runs pg_dump/pg_restore (/opt/bin) from the pgclient layer.
    aws_lambda_layer_version.ducklake_pgclient.arn,
  ]

  environment {
    variables = {
      # The operational actions target production via explicit event params (catalog_reinit,
      # reconcile_columns, merge_ops, clone_catalog); EXTENSION_DIRECTORY and
      # FIELD_SEMANTICS_PATH are the only env-pinned values this function still reads --
      # DUCKLAKE_DATA_PATH/DUCKLAKE_META_SCHEMA/GC_BREAKER_* were only consumed by the scheduled
      # smoke cadences (merge/gc/hot_merge/breaker_probe), which moved to
      # ducklake_maintenance_smoke.tf in the T2.18 c9 split.
      DUCKLAKE_EXTENSION_DIRECTORY = local.ducklake_extension_dir
      # catalog_reinit's create_scd2_tables + reconcile_columns/restore_drill's field-spec
      # resolution load the field-semantics contract bundled into the zip (manifest assets[]).
      DUCKLAKE_FIELD_SEMANTICS_PATH = "/var/task/config/lambda/ducklake/field_semantics.yaml"
    }
  }

  depends_on = [
    aws_iam_role_policy.ducklake_maintenance,
    aws_cloudwatch_log_group.ducklake_maintenance,
  ]

  tags = {
    Name    = "DuckLake Maintenance Admin"
    Purpose = "T2.18 ducklake_maintenance admin singleton - production-destructive + operational verbs"
  }

  # Decision 125 physical decoupling: code deploys go via build_lambda --ducklake-only --deploy
  # (update-function-code), not terraform. Without this, every rebuild's non-reproducible zip bytes
  # trip a Terraform diff on this IAM-gated apply path (rec-2646/rec-2654).
  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

# ---------------------------------------------------------------------------
# Function URL (AWS_IAM) -- admin invoke ingress for the operational actions.
# ---------------------------------------------------------------------------

resource "aws_lambda_function_url" "ducklake_maintenance" {
  function_name      = aws_lambda_function.ducklake_maintenance.function_name
  authorization_type = "AWS_IAM"
}

# ---------------------------------------------------------------------------
# The daily merge / weekly GC / 6h hot_merge EventBridge rules+targets+permissions MOVED to
# ducklake_maintenance_smoke.tf (T2.18 c9 split) -- the rule resources use `moved {}` blocks there
# to preserve their AWS name/ARN; only merge_ops stays scheduled on this admin function below.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# EventBridge prod-merge rule: every-6h non-destructive merge of ALL live ops_* SCD2 table pairs
# in the production catalog (ducklake_ops @ s3://.../ducklake/). Staggered to :30 (off the 6-hourly
# hot_merge at :00) to avoid throttle under reserved_concurrent_executions=1. Non-destructive:
# merge_ops dispatches merge_adjacent_files only -- no expire/cleanup/orphan (gated by rec-2113/T2.26).
# Cadence raised from daily (cron(30 4 * * ? *)) to every 6h by neon-egress-reduction (D3a): paying
# down ops_* small-file growth faster shrinks the per-query ducklake_file_column_stats footprint that
# drives every read's Neon metadata egress (ducklake #859).
# No new IAM: reuses the existing maintenance role (already grants S3 RW on the prod prefix).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "ducklake_maintenance_merge_ops" {
  name                = "agent-platform-ducklake-maintenance-merge-ops"
  description         = "Every-6h production DuckLake ops_* non-destructive merge (T2.18 Phase-4 / Decision 84; neon-egress D3a). cron every 6h at :30 UTC."
  schedule_expression = "cron(30 */6 * * ? *)"
  state               = "ENABLED"

  tags = {
    Name    = "DuckLake Maintenance Prod Merge Ops Schedule"
    Purpose = "T2.18 Phase-4 every-6h production ops non-destructive merge - neon-egress D3a"
  }
}

resource "aws_cloudwatch_event_target" "ducklake_maintenance_merge_ops" {
  rule      = aws_cloudwatch_event_rule.ducklake_maintenance_merge_ops.name
  target_id = "ducklake-maintenance-merge-ops"
  arn       = aws_lambda_function.ducklake_maintenance.arn
  input     = jsonencode({ action = "merge_ops", data_path = local.ducklake_prod_data_path, meta_schema = "ducklake_ops" })
}

resource "aws_lambda_permission" "ducklake_maintenance_merge_ops" {
  statement_id  = "AllowEventBridgeMergeOps"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ducklake_maintenance.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ducklake_maintenance_merge_ops.arn
}

# ---------------------------------------------------------------------------
# Circuit-breaker CloudWatch metric alarm.
# Fires when MaintenanceBreakerTrip >= 1 in a 5-minute window.
# alarm_actions wired to shared SNS topic (FP-B / Decision 39).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ducklake_maintenance_breaker" {
  alarm_name          = "ducklake-maintenance-circuit-breaker"
  alarm_description   = "DuckLake maintenance GC circuit breaker tripped (>20% files or >10 GiB). T2.18 / CD.33 H1."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "MaintenanceBreakerTrip"
  namespace           = "DuckLakeMaintenance"
  period              = 300
  statistic           = "Sum"
  threshold           = 1

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  treat_missing_data = "notBreaching"

  tags = {
    Name    = "DuckLake Maintenance Breaker Alarm"
    Purpose = "T2.18 CD.33 H1 circuit breaker alert"
  }
}

# ---------------------------------------------------------------------------
# Outputs -- admin-invoked operational actions only (the c9 smoke gates resolve
# ducklake_maintenance_smoke_function_url instead; see ducklake_maintenance_smoke.tf).
# ---------------------------------------------------------------------------

output "ducklake_maintenance_function_url" {
  description = "AWS_IAM Function URL for the ducklake_maintenance admin Lambda (operational actions)."
  value       = aws_lambda_function_url.ducklake_maintenance.function_url
}

output "ducklake_maintenance_function_name" {
  description = "ducklake_maintenance Lambda function name (build_lambda --ducklake-only --deploy target)."
  value       = aws_lambda_function.ducklake_maintenance.function_name
}
