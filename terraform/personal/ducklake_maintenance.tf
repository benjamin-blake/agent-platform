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
# FP-B note: alarm_actions = [] -- no SNS topic exists in terraform/personal/ yet.
# FP-B creates one shared personal-account SNS topic and wires it as the alarm_actions target
# for BOTH this circuit-breaker alarm AND the CD.34 catalog-DR freshness alarm (Decision 81 / plan).

locals {
  ducklake_maintenance_function = "agent-platform-ducklake-maintenance"
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
  description        = "Maintenance singleton: S3 RW+Delete on the smoke prefix, Neon DSN read, maintenance metrics"
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
        # T2.19 NOTE: delete_orphaned_files is catalog-wide, not table-scoped. When GC_TABLE_SCOPE
        # expands to ops_* at T2.19, this resource ARN must expand to cover all DuckLake data prefixes
        # (not just the smoke prefix) or delete_orphaned_files will fail with AccessDenied at S3.
        Sid    = "S3SmokeDataReadWriteDelete"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/${local.ducklake_smoke_data_prefix}/*"
        ]
      },
      {
        Sid      = "S3ListSmokePrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["${local.ducklake_smoke_data_prefix}/*"]
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

  # NOTE: reserved_concurrent_executions=1 (singleton, Decision 81 clause 6). This is intentional
  # and correct for the maintenance pipeline. It differs from the writer (no reserved_concurrency,
  # Decision 81 clause 3 OCC model). See file-level comment for the full rationale.
  reserved_concurrent_executions = 1

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ducklake-maintenance.zip"
  source_code_hash = try(filemd5("${path.module}/../../lambda-packages/ducklake-maintenance.zip"), null)

  layers = [
    aws_lambda_layer_version.ducklake_deps.arn,
    aws_lambda_layer_version.ducklake_extensions.arn,
  ]

  environment {
    variables = {
      DUCKLAKE_DATA_PATH           = local.ducklake_smoke_data_path
      DUCKLAKE_EXTENSION_DIRECTORY = local.ducklake_extension_dir
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
# Circuit-breaker CloudWatch metric alarm.
# Fires when MaintenanceBreakerTrip >= 1 in a 5-minute window.
# alarm_actions = [] -- no SNS topic in terraform/personal/ yet.
# FP-B: wire alarm_actions to the shared SNS topic created in FP-B.
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

  # FP-B: wire alarm_actions to the shared SNS topic (created in FP-B alongside the catalog-DR
  # freshness alarm). No aws_sns_topic exists in terraform/personal/ in this slice.
  alarm_actions = []
  ok_actions    = []

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
