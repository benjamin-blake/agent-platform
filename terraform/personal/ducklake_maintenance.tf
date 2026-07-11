# DuckLake maintenance singleton Lambda (T2.18 / CD.33, Decision 81).
#
# Implements two EventBridge-scheduled cadences (Decision 62 / CD.29 -- Lambda over new GH Actions
# surface for non-CI scheduled work):
#   daily  cron(0 4 * * ? *) -> action=merge  (non-destructive merge only)
#   weekly cron(0 5 ? * SUN *) -> action=gc   (full guarded GC with circuit breaker)
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
#   1. build_lambda --ducklake-only       (upload all 3 zips + 2 layers to S3)
#   2. terraform plan -> human review -> terraform apply via agent_platform_admin
#   3. build_lambda --ducklake-only --deploy  (update the 3 function code pointers from S3)
#
# CODE/INFRA COUPLING (Decision 125, environment-taxonomy.md section 5): RESOLVED. The
# aws_lambda_function resource below now carries a lifecycle block ignoring source_code_hash
# changes, so code-only redeploys no longer surface as a Terraform diff on this apply path. Code
# deploys now go via step 3 above (`build_lambda --ducklake-only --deploy`) -- knowingly-interim
# break-glass status (Decision 125 pt 2-5) pending the governed code-deploy CD channel (rec-2646
# residual scope).
#
# FP-B (2026-06-07): shared SNS topic (sns_alerts.tf) created and wired as the alarm_actions
# target for BOTH this circuit-breaker alarm AND the CD.34 catalog-DR freshness alarm.
# Also added: hot_merge EventBridge rule/target/permission + env-tunable breaker thresholds.

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
# Write-scoped execution role: S3 Get/Put/Delete/List on the smoke prefix, DSN read,
# DuckLakeMaintenance CloudWatch metrics, logs.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ducklake_maintenance" {
  name               = "agent-platform-ducklake-maintenance"
  description        = "Maintenance singleton: S3 RW+Delete on the smoke + production prefixes, Neon DSN read, maintenance metrics"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
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
        # T2.19: the operational actions write to the PRODUCTION prefix -- seed_ops_recommendations and
        # catalog_reinit at ducklake/, and restore_drill at ducklake/_restore_drill/ (a sub-prefix). The
        # scheduled merge/gc still touch the smoke prefix. delete_orphaned_files is catalog-wide, so both
        # data prefixes are covered here.
        Sid    = "S3DataReadWriteDelete"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/${local.ducklake_prod_data_prefix}/*",
          "${aws_s3_bucket.data_lake.arn}/${local.ducklake_smoke_data_prefix}/*",
        ]
      },
      {
        Sid      = "S3ListDataPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.ducklake_prod_data_prefix}/*", "${local.ducklake_smoke_data_prefix}/*"]
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
  description   = "T2.18 DuckLake maintenance singleton (CD.33/Decision 81). Daily merge + weekly guarded GC."
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
      # Scheduled merge/gc operate on the SMOKE catalog (relocated to its own ducklake_smoke
      # meta-schema -- rec-2099). The operational actions target production via explicit event params.
      DUCKLAKE_DATA_PATH           = local.ducklake_smoke_data_path
      DUCKLAKE_META_SCHEMA         = "ducklake_smoke"
      DUCKLAKE_EXTENSION_DIRECTORY = local.ducklake_extension_dir
      # The seed/catalog actions schema_gate + write_scd2, which load the field-semantics contract
      # bundled into the zip (manifest assets[]).
      DUCKLAKE_FIELD_SEMANTICS_PATH = "/var/task/config/lambda/ducklake/field_semantics.yaml"
      # FP-B env-tunable GC circuit-breaker thresholds (CD.34 co-tuning mechanism).
      # FP-A defaults retained as the shipped values; change ONLY via a Decision superseding CD.33.
      # Tuning to pass a gate is a Decision-55 violation.
      GC_BREAKER_FILE_FRACTION = "0.20"
      GC_BREAKER_BYTES         = "10737418240" # 10 GiB
    }
  }

  depends_on = [
    aws_iam_role_policy.ducklake_maintenance,
    aws_cloudwatch_log_group.ducklake_maintenance,
  ]

  tags = {
    Name    = "DuckLake Maintenance"
    Purpose = "T2.18 ducklake_maintenance singleton"
  }

  # Decision 125 physical decoupling: code deploys go via build_lambda --ducklake-only --deploy
  # (update-function-code), not terraform. Without this, every rebuild's non-reproducible zip bytes
  # trip a Terraform diff on this IAM-gated apply path (rec-2646/rec-2654).
  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

# ---------------------------------------------------------------------------
# Function URL (AWS_IAM) -- smoke-test invoke ingress for VP steps 9-11.
# ---------------------------------------------------------------------------

resource "aws_lambda_function_url" "ducklake_maintenance" {
  function_name      = aws_lambda_function.ducklake_maintenance.function_name
  authorization_type = "AWS_IAM"
}

# ---------------------------------------------------------------------------
# EventBridge schedule rules + targets + Lambda permissions.
# Two rules: daily merge (04:00 UTC) and weekly GC (05:00 UTC Sunday).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "ducklake_maintenance_merge" {
  name                = "agent-platform-ducklake-maintenance-merge"
  description         = "Daily DuckLake non-destructive merge (T2.18 / CD.33). cron 04:00 UTC."
  schedule_expression = "cron(0 4 * * ? *)"
  state               = "ENABLED"

  tags = {
    Name    = "DuckLake Maintenance Merge Schedule"
    Purpose = "T2.18 daily non-destructive merge"
  }
}

resource "aws_cloudwatch_event_target" "ducklake_maintenance_merge" {
  rule      = aws_cloudwatch_event_rule.ducklake_maintenance_merge.name
  target_id = "ducklake-maintenance-merge"
  arn       = aws_lambda_function.ducklake_maintenance.arn
  input     = jsonencode({ action = "merge" })
}

resource "aws_lambda_permission" "ducklake_maintenance_merge" {
  statement_id  = "AllowEventBridgeMerge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ducklake_maintenance.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ducklake_maintenance_merge.arn
}

resource "aws_cloudwatch_event_rule" "ducklake_maintenance_gc" {
  name                = "agent-platform-ducklake-maintenance-gc"
  description         = "Weekly DuckLake guarded GC (T2.18 / CD.33). cron 05:00 UTC Sunday."
  schedule_expression = "cron(0 5 ? * SUN *)"
  state               = "ENABLED"

  tags = {
    Name    = "DuckLake Maintenance GC Schedule"
    Purpose = "T2.18 weekly guarded GC"
  }
}

resource "aws_cloudwatch_event_target" "ducklake_maintenance_gc" {
  rule      = aws_cloudwatch_event_rule.ducklake_maintenance_gc.name
  target_id = "ducklake-maintenance-gc"
  arn       = aws_lambda_function.ducklake_maintenance.arn
  input     = jsonencode({ action = "gc" })
}

resource "aws_lambda_permission" "ducklake_maintenance_gc" {
  statement_id  = "AllowEventBridgeGc"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ducklake_maintenance.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ducklake_maintenance_gc.arn
}

# ---------------------------------------------------------------------------
# EventBridge hot_merge rule: higher-frequency merge cadence (T2.18 FP-B / CD.34).
# Runs merge_adjacent_files ONLY over HOT_TABLE_SCOPE (no GC/deletion).
# Cadence: every 6h -- bounds small-file COUNT between weekly GC passes.
# T2.19 forward pointer: the real high-write-rate ops_* tables are wired at T2.19.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "ducklake_maintenance_hot_merge" {
  name                = "agent-platform-ducklake-maintenance-hot-merge"
  description         = "Higher-frequency DuckLake merge-only cadence (T2.18 FP-B / CD.34). cron every 6h."
  schedule_expression = "cron(0 */6 * * ? *)"
  state               = "ENABLED"

  tags = {
    Name    = "DuckLake Maintenance Hot Merge Schedule"
    Purpose = "T2.18 FP-B higher-frequency merge-only cadence"
  }
}

resource "aws_cloudwatch_event_target" "ducklake_maintenance_hot_merge" {
  rule      = aws_cloudwatch_event_rule.ducklake_maintenance_hot_merge.name
  target_id = "ducklake-maintenance-hot-merge"
  arn       = aws_lambda_function.ducklake_maintenance.arn
  input     = jsonencode({ action = "hot_merge" })
}

resource "aws_lambda_permission" "ducklake_maintenance_hot_merge" {
  statement_id  = "AllowEventBridgeHotMerge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ducklake_maintenance.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ducklake_maintenance_hot_merge.arn
}

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
# Outputs -- consumed by the [post-deploy] smoke-test invoke gates.
# ---------------------------------------------------------------------------

output "ducklake_maintenance_function_url" {
  description = "AWS_IAM Function URL for the ducklake_maintenance Lambda (T2.18 smoke gates)."
  value       = aws_lambda_function_url.ducklake_maintenance.function_url
}

output "ducklake_maintenance_function_name" {
  description = "ducklake_maintenance Lambda function name (build_lambda --ducklake-only --deploy target)."
  value       = aws_lambda_function.ducklake_maintenance.function_name
}
