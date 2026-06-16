# DuckLake catalog disaster-recovery Lambda (T2.18 FP-B / CD.34, Decision 82).
#
# Daily pg_dump --format=custom --serializable-deferrable of the Neon catalog to a
# dedicated versioned + lifecycle-managed S3 bucket. Emits CatalogDumpSuccess to CloudWatch
# DuckLakeCatalogDR namespace. A >25h freshness alarm pages via the shared SNS topic when
# a daily dump is missed.
#
# pg_dump is provided by the ducklake-pgclient layer (/opt/bin/pg_dump + /opt/lib/libpq.so;
# PG16, AL2023/x86_64). No pip wheel exists for pg_dump; the binary is vendored to S3 and
# fetched at build time by build_pgclient_layer (scripts/build_lambda.py).
#
# ---------------------------------------------------------------------------
# APPLY POSTURE (Decision 35 + 77): HUMAN-GATED via agent_platform_admin.
# ---------------------------------------------------------------------------
# Creates a NEW IAM role + inline policy, which trips the Decision-77 deterministic fail-closed
# guard (scripts/terraform_apply_guard.py). Apply routes to the MANUAL agent_platform_admin
# path. IAM must precede the code deploy:
#   1. build_lambda --ducklake-only       (upload catalog-dr zip + pgclient layer to S3)
#   2. terraform plan -> human review -> terraform apply via agent_platform_admin
#   3. build_lambda --ducklake-only --deploy  (update the DR function code pointer from S3)

locals {
  ducklake_catalog_dr_function = "agent-platform-ducklake-catalog-dr"
  ducklake_dr_bucket_name      = "agent-platform-ducklake-catalog-dr"
}

# ---------------------------------------------------------------------------
# DR S3 bucket: versioned + SSE + public-access-block + lifecycle.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "ducklake_catalog_dr" {
  bucket = local.ducklake_dr_bucket_name

  tags = {
    Name    = "DuckLake Catalog DR"
    Purpose = "T2.18 FP-B catalog disaster-recovery dump storage - CD.34"
  }
}

resource "aws_s3_bucket_versioning" "ducklake_catalog_dr" {
  bucket = aws_s3_bucket.ducklake_catalog_dr.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "ducklake_catalog_dr" {
  bucket = aws_s3_bucket.ducklake_catalog_dr.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "ducklake_catalog_dr" {
  bucket = aws_s3_bucket.ducklake_catalog_dr.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "ducklake_catalog_dr" {
  bucket = aws_s3_bucket.ducklake_catalog_dr.id

  rule {
    id     = "dr-dump-expiry"
    status = "Enabled"

    expiration {
      # 30-day retention (tunable to 7). See CD.34 O-2 / CD.33 Decision 82.
      # On any DuckLake/DuckDB engine bump (OQ.12), re-baseline this window.
      days = 30
    }

    noncurrent_version_expiration {
      # Retain >=7 days of prior versions (matches FILE_CLEANUP_GRACE_DAYS). Daily dumps use
      # unique timestamped keys so overwrites are not expected, but versioning still protects
      # against an accidental overwrite/partial-failure: keep the immediately-preceding version
      # restorable for a week before permanent deletion (code-review H1).
      noncurrent_days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }

    filter {}
  }
}

# ---------------------------------------------------------------------------
# CloudWatch log group (pre-created so the exec-role grant can be scoped to its ARN).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ducklake_catalog_dr" {
  name              = "/aws/lambda/${local.ducklake_catalog_dr_function}"
  retention_in_days = 14

  tags = {
    Name    = "DuckLake Catalog DR Logs"
    Purpose = "T2.18 FP-B ducklake_catalog_dr Lambda"
  }
}

# ---------------------------------------------------------------------------
# Exec role + inline policy: DSN read, DR bucket Put/List, metrics, logs.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ducklake_catalog_dr" {
  name               = "agent-platform-ducklake-catalog-dr"
  description        = "Catalog DR Lambda: Neon DSN read, DR bucket Put/List, DuckLakeCatalogDR metrics"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "ducklake_catalog_dr" {
  name = "DuckLakeCatalogDRRuntime"
  role = aws_iam_role.ducklake_catalog_dr.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.ducklake_catalog_dr.arn}:*"]
      },
      {
        Sid    = "NeonDsnRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        # pragma: allowlist secret
        Resource = [aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn]
      },
      {
        Sid      = "DRBucketWrite"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${aws_s3_bucket.ducklake_catalog_dr.arn}/*"]
      },
      {
        Sid      = "DRBucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.ducklake_catalog_dr.arn]
      },
      {
        # PutMetricData does not support resource-level scoping; constrain to the DR namespace.
        Sid      = "CloudWatchMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "DuckLakeCatalogDR"
          }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# pgclient layer version (pg_dump 16 + libpq.so + transitive libs).
# Built by build_pgclient_layer in scripts/build_lambda.py (S3/CDN fetch at build time).
# ---------------------------------------------------------------------------

resource "aws_lambda_layer_version" "ducklake_pgclient" {
  layer_name               = "ducklake-pgclient"
  description              = "pg_dump 16 + libpq.so + transitive libs under /opt/bin + /opt/lib (T2.18 FP-B)"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ducklake-pgclient-layer.zip"
  source_code_hash = try(filemd5("${path.module}/../../lambda-packages/ducklake-pgclient-layer.zip"), null)
}

# ---------------------------------------------------------------------------
# DR Lambda function.
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "ducklake_catalog_dr" {
  function_name = local.ducklake_catalog_dr_function
  description   = "T2.18 FP-B DuckLake catalog DR Lambda (CD.34/Decision 82). Daily pg_dump -> S3."
  role          = aws_iam_role.ducklake_catalog_dr.arn
  runtime       = "python3.12"
  handler       = "src.lambdas.ducklake_catalog_dr.handler.handler"
  architectures = ["x86_64"]
  timeout       = 300
  memory_size   = 512

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ducklake-catalog-dr.zip"
  source_code_hash = try(filemd5("${path.module}/../../lambda-packages/ducklake-catalog-dr.zip"), null)

  layers = [
    aws_lambda_layer_version.ducklake_pgclient.arn,
    # ducklake-deps supplies PyYAML (+ boto3): catalog_dr.py imports src.common.ducklake_runtime
    # (for emit_metric / PINNED_DUCKDB_VERSION / fetch_dsn), whose module-level `import yaml` fails
    # without it. duckdb is imported lazily and never exercised by the DR path (no connection opened).
    aws_lambda_layer_version.ducklake_deps.arn,
  ]

  environment {
    variables = {
      DUCKLAKE_DR_BUCKET = local.ducklake_dr_bucket_name
    }
  }

  depends_on = [
    aws_iam_role_policy.ducklake_catalog_dr,
    aws_cloudwatch_log_group.ducklake_catalog_dr,
  ]

  tags = {
    Name    = "DuckLake Catalog DR"
    Purpose = "T2.18 FP-B catalog disaster-recovery Lambda"
  }
}

# ---------------------------------------------------------------------------
# Function URL (AWS_IAM) -- smoke-test invoke ingress.
# ---------------------------------------------------------------------------

resource "aws_lambda_function_url" "ducklake_catalog_dr" {
  function_name      = aws_lambda_function.ducklake_catalog_dr.function_name
  authorization_type = "AWS_IAM"
}

# ---------------------------------------------------------------------------
# EventBridge schedule: weekly cron(0 3 ? * SUN *) -- 03:00 UTC Sunday.
#
# Lowered from daily to weekly by neon-egress-reduction (D1): the daily full-catalog pg_dump was a
# session-independent Neon egress line (CD.34 called it "a negligible add-on" -- true for storage,
# FALSE for egress). Paid-tier Neon provides 7-day PITR for finer-grained recovery BETWEEN the weekly
# full dumps, so the durability floor is preserved while the pg_dump egress line drops ~7x.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "ducklake_catalog_dr" {
  name                = "agent-platform-ducklake-catalog-dr"
  description         = "Weekly DuckLake catalog DR pg_dump (T2.18 FP-B / CD.34; neon-egress D1). cron 03:00 UTC Sunday."
  schedule_expression = "cron(0 3 ? * SUN *)"
  state               = "ENABLED"

  tags = {
    Name    = "DuckLake Catalog DR Schedule"
    Purpose = "T2.18 FP-B weekly catalog DR (neon-egress D1)"
  }
}

resource "aws_cloudwatch_event_target" "ducklake_catalog_dr" {
  rule      = aws_cloudwatch_event_rule.ducklake_catalog_dr.name
  target_id = "ducklake-catalog-dr"
  arn       = aws_lambda_function.ducklake_catalog_dr.arn
}

resource "aws_lambda_permission" "ducklake_catalog_dr" {
  statement_id  = "AllowEventBridgeCatalogDR"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ducklake_catalog_dr.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ducklake_catalog_dr.arn
}

# ---------------------------------------------------------------------------
# Freshness alarm: ~8-day lookback via evaluation_periods math.
#
# CloudWatch's period ceiling is 86400s (24h), so the lookback is built from hourly periods:
#   period=3600, evaluation_periods=192, datapoints_to_alarm=192
# meaning "in all 192 of the last 192 hourly periods (~8 days), CatalogDumpSuccess < 1".
# CO-REQUIRED with the weekly schedule (neon-egress D1): the prior >25h window (25/25) would sit in
# perpetual ALARM ~6 days out of every 7 under a weekly dump and page SNS daily. An ~8-day window
# clears within a day of each successful weekly dump while still catching a genuinely missed week.
# treat_missing_data=breaching: missing datapoints (no invocation) are counted as failing.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ducklake_catalog_dr_freshness" {
  alarm_name          = "ducklake-catalog-dr-freshness"
  alarm_description   = "DuckLake catalog DR missed: no CatalogDumpSuccess in ~8 days. T2.18 FP-B CD.34 (neon-egress D1 weekly cadence)."
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 192
  datapoints_to_alarm = 192
  metric_name         = "CatalogDumpSuccess"
  namespace           = "DuckLakeCatalogDR"
  period              = 3600
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = {
    Name    = "DuckLake Catalog DR Freshness Alarm"
    Purpose = "T2.18 FP-B CD.34 over-25h freshness guard"
  }
}

# ---------------------------------------------------------------------------
# Outputs.
# ---------------------------------------------------------------------------

output "ducklake_catalog_dr_function_url" {
  description = "AWS_IAM Function URL for the ducklake_catalog_dr Lambda (T2.18 FP-B smoke gate)."
  value       = aws_lambda_function_url.ducklake_catalog_dr.function_url
}

output "ducklake_catalog_dr_function_name" {
  description = "ducklake_catalog_dr Lambda function name."
  value       = aws_lambda_function.ducklake_catalog_dr.function_name
}

output "ducklake_catalog_dr_bucket" {
  description = "DR S3 bucket name (versioned + lifecycle-managed)."
  value       = aws_s3_bucket.ducklake_catalog_dr.bucket
}
