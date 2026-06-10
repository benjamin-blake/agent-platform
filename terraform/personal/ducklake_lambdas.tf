# DuckLake operational-lakehouse runtime Lambdas (T2.17 / CD.33, Decision 81).
#
# First Lambda functions in the personal account: ducklake_writer + ducklake_reader. They ATTACH to
# the live Neon serverless-Postgres DuckLake catalog over TLS (NO VPC attach -- Neon is a public TLS
# endpoint) with the ducklake/httpfs/postgres DuckDB extensions baked into a layer (extension_directory
# + autoload/autoinstall off + custom_extension_repository fail-closed). Function URLs are AWS_IAM
# (SigV4-signed; unsigned -> 403). The two roles are write-scoped / read-scoped: the reader has S3
# GetObject only, so a write from the read role is denied (closed-boundary proof).
#
# ---------------------------------------------------------------------------
# APPLY POSTURE (Decision 35 + 77): HUMAN-GATED via agent_platform_admin.
# ---------------------------------------------------------------------------
# These resources create NEW IAM roles + inline policies, which trip the Decision-77 deterministic
# guard (scripts/terraform_apply_guard.py, fail-closed on any IAM/trust change). The whole
# terraform/personal apply for this change therefore routes to the MANUAL agent_platform_admin path,
# NOT push-to-main auto-apply. IAM must precede the code deploy (terraform CLAUDE.md IAM-precedence):
#   1. build_lambda --ducklake-only  (uploads the 2 zips + 2 layer zips to S3)
#   2. terraform -chdir=terraform/personal plan  -> present to human -> apply via agent_platform_admin
#   3. build_lambda --ducklake-only --deploy  (updates the two functions' code from S3)
#
# SINGLE-PORTAL NOTE (Decision 78/81): at T2.19 these Function URLs become the CLOSED ops boundary --
# the writer is the sole ops_* write authority, the reader the sole read authority. ops_data_portal
# transits them (transport-swapped behind OPS_STORAGE_BACKEND); the caller surface is unchanged. This
# apply widens both roles to the production ducklake/ data path + flips DUCKLAKE_DATA_PATH smoke->prod.

locals {
  ducklake_smoke_data_path   = "s3://${aws_s3_bucket.data_lake.bucket}/ducklake-neon-smoke/"
  ducklake_smoke_data_prefix = "ducklake-neon-smoke"
  # T2.19 production ops data path. The generalized writer/reader operate on the ops_* SCD2 tables
  # here at cutover; smoke access is RETAINED for the T2.17 gates + rollback (Decision 78 cl.7).
  ducklake_prod_data_path   = "s3://${aws_s3_bucket.data_lake.bucket}/ducklake/"
  ducklake_prod_data_prefix = "ducklake"
  ducklake_writer_function  = "agent-platform-ducklake-writer"
  ducklake_reader_function  = "agent-platform-ducklake-reader"
  ducklake_extension_dir    = "/opt/duckdb_extensions"
}

# ---------------------------------------------------------------------------
# Layers (from S3) -- duckdb==1.5.3 + deps, and the 3 baked extensions. The layer zips are uploaded
# to S3 by build_lambda BEFORE the apply; the source_code_hash is try()-guarded so a plan without the
# local zip (e.g. CI validate) does not fail.
# ---------------------------------------------------------------------------

resource "aws_lambda_layer_version" "ducklake_deps" {
  layer_name          = "ducklake-deps"
  description         = "DuckLake deps: duckdb==1.5.3, psycopg2-binary, python-ulid, pyyaml (T2.17)"
  s3_bucket           = aws_s3_bucket.data_lake.id
  s3_key              = "lambda-packages/ducklake-deps-layer.zip"
  compatible_runtimes = ["python3.12"]
  source_code_hash    = try(filemd5("${path.module}/../../lambda-packages/ducklake-deps-layer.zip"), null)
}

resource "aws_lambda_layer_version" "ducklake_extensions" {
  layer_name          = "ducklake-extensions"
  description         = "Baked DuckDB v1.5.3 linux_amd64 extensions: ducklake, httpfs, postgres_scanner (T2.17)"
  s3_bucket           = aws_s3_bucket.data_lake.id
  s3_key              = "lambda-packages/ducklake-extensions-layer.zip"
  compatible_runtimes = ["python3.12"]
  source_code_hash    = try(filemd5("${path.module}/../../lambda-packages/ducklake-extensions-layer.zip"), null)
}

# ---------------------------------------------------------------------------
# CloudWatch log groups (pre-created so the execution-role grant can be scoped to their ARNs).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ducklake_writer" {
  name              = "/aws/lambda/${local.ducklake_writer_function}"
  retention_in_days = 14

  tags = {
    Name    = "DuckLake Writer Logs"
    Purpose = "T2.17 ducklake_writer runtime"
  }
}

resource "aws_cloudwatch_log_group" "ducklake_reader" {
  name              = "/aws/lambda/${local.ducklake_reader_function}"
  retention_in_days = 14

  tags = {
    Name    = "DuckLake Reader Logs"
    Purpose = "T2.17 ducklake_reader runtime"
  }
}

# ---------------------------------------------------------------------------
# Write-scoped execution role: S3 read+write on the smoke prefix, DSN secret read, metrics, logs.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ducklake_writer" {
  name               = "agent-platform-ducklake-writer"
  description        = "Write-scoped DuckLake runtime: S3 RW on ducklake/ + smoke prefixes, Neon DSN read, metrics"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "ducklake_writer" {
  name = "DuckLakeWriterRuntime"
  role = aws_iam_role.ducklake_writer.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.ducklake_writer.arn}:*"]
      },
      {
        Sid      = "NeonDsnRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn]
      },
      {
        # Writer is the SOLE write authority for ops_* (CD.33 clause 4): RW on the production
        # ducklake/ data path AND the retained smoke prefix (T2.17 gates / rollback).
        Sid    = "S3DataReadWrite"
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
        # PutMetricData does not support resource-level scoping; constrain to the writer namespace.
        Sid      = "CloudWatchMetrics"
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "DuckLakeWriter"
          }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Read-scoped execution role: S3 GetObject ONLY on the smoke prefix (no Put/Delete -> writes denied),
# DSN secret read, logs. No metrics.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ducklake_reader" {
  name               = "agent-platform-ducklake-reader"
  description        = "Read-scoped DuckLake runtime: S3 GetObject on ducklake/ + smoke prefixes only, Neon DSN read"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "ducklake_reader" {
  name = "DuckLakeReaderRuntime"
  role = aws_iam_role.ducklake_reader.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.ducklake_reader.arn}:*"]
      },
      {
        Sid      = "NeonDsnRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.ducklake_neon_catalog_dsn.arn]
      },
      {
        # GetObject ONLY -- no PutObject/DeleteObject. A DuckLake write (Parquet PutObject) from this
        # role is denied at S3, which is the closed-boundary proof (write_probe -> write_denied=true).
        # Read-only on the production ducklake/ data path AND the retained smoke prefix.
        Sid    = "S3DataReadOnly"
        Effect = "Allow"
        Action = ["s3:GetObject"]
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
    ]
  })
}

# ---------------------------------------------------------------------------
# The two Lambda functions (from S3). source_code_hash try()-guarded; code is updated post-apply by
# build_lambda --ducklake-only --deploy.
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "ducklake_writer" {
  function_name = local.ducklake_writer_function
  description   = "T2.17 DuckLake write-scoped runtime (CD.33). Smoke-test ingress only (Decision 78/81)."
  role          = aws_iam_role.ducklake_writer.arn
  runtime       = "python3.12"
  handler       = "src.lambdas.ducklake_writer.handler.handler"
  architectures = ["x86_64"]
  timeout       = 120
  memory_size   = 3008 # Retained as baseline headroom per human decision (Decision 82 frame correction). Branch-P rationale superseded: EC8 now measures N concurrent invocations (each its own vCPU), not in-container thread contention.

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ducklake-writer.zip"
  source_code_hash = try(filemd5("${path.module}/../../lambda-packages/ducklake-writer.zip"), null)

  layers = [
    aws_lambda_layer_version.ducklake_deps.arn,
    aws_lambda_layer_version.ducklake_extensions.arn,
  ]

  environment {
    variables = {
      DUCKLAKE_DATA_PATH            = local.ducklake_prod_data_path
      DUCKLAKE_EXTENSION_DIRECTORY  = local.ducklake_extension_dir
      DUCKLAKE_FIELD_SEMANTICS_PATH = "/var/task/config/lambda/ducklake/field_semantics.yaml"
    }
  }

  depends_on = [
    aws_iam_role_policy.ducklake_writer,
    aws_cloudwatch_log_group.ducklake_writer,
  ]

  tags = {
    Name    = "DuckLake Writer"
    Purpose = "T2.17 ducklake_writer runtime"
  }
}

resource "aws_lambda_function" "ducklake_reader" {
  function_name = local.ducklake_reader_function
  description   = "T2.17 DuckLake read-scoped runtime (CD.33). Smoke-test ingress only (Decision 78/81)."
  role          = aws_iam_role.ducklake_reader.arn
  runtime       = "python3.12"
  handler       = "src.lambdas.ducklake_reader.handler.handler"
  architectures = ["x86_64"]
  timeout       = 120
  memory_size   = 1024

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ducklake-reader.zip"
  source_code_hash = try(filemd5("${path.module}/../../lambda-packages/ducklake-reader.zip"), null)

  layers = [
    aws_lambda_layer_version.ducklake_deps.arn,
    aws_lambda_layer_version.ducklake_extensions.arn,
  ]

  environment {
    variables = {
      DUCKLAKE_DATA_PATH            = local.ducklake_prod_data_path
      DUCKLAKE_EXTENSION_DIRECTORY  = local.ducklake_extension_dir
      DUCKLAKE_FIELD_SEMANTICS_PATH = "/var/task/config/lambda/ducklake/field_semantics.yaml"
    }
  }

  depends_on = [
    aws_iam_role_policy.ducklake_reader,
    aws_cloudwatch_log_group.ducklake_reader,
  ]

  tags = {
    Name    = "DuckLake Reader"
    Purpose = "T2.17 ducklake_reader runtime"
  }
}

# ---------------------------------------------------------------------------
# Function URLs (AWS_IAM). SigV4-signed requests from a principal with lambda:InvokeFunctionUrl pass;
# unsigned requests return 403 (EC4). CD.10 / NS.5 ingress surface, unaffected by the no-VPC config.
# ---------------------------------------------------------------------------

resource "aws_lambda_function_url" "ducklake_writer" {
  function_name      = aws_lambda_function.ducklake_writer.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function_url" "ducklake_reader" {
  function_name      = aws_lambda_function.ducklake_reader.function_name
  authorization_type = "AWS_IAM"
}

# ---------------------------------------------------------------------------
# Outputs -- consumed by the [post-deploy] smoke-test invoke gates (ducklake_neon_smoke_test).
# ---------------------------------------------------------------------------

output "ducklake_writer_function_url" {
  description = "AWS_IAM Function URL for the ducklake_writer Lambda (T2.17 smoke gates)."
  value       = aws_lambda_function_url.ducklake_writer.function_url
}

output "ducklake_reader_function_url" {
  description = "AWS_IAM Function URL for the ducklake_reader Lambda (T2.17 smoke gates)."
  value       = aws_lambda_function_url.ducklake_reader.function_url
}

output "ducklake_writer_function_name" {
  description = "ducklake_writer Lambda function name (build_lambda --ducklake-only --deploy target)."
  value       = aws_lambda_function.ducklake_writer.function_name
}

output "ducklake_reader_function_name" {
  description = "ducklake_reader Lambda function name (build_lambda --ducklake-only --deploy target)."
  value       = aws_lambda_function.ducklake_reader.function_name
}

# ---------------------------------------------------------------------------
# SSM endpoint-discovery parameters (Decision 79 SSOT / Decision 81 cl.7 closed boundary).
# Published by push-to-main auto-apply (non-IAM, non-destroy: guard passes).
# Runtime clients resolve the Function URL via ssm:GetParameter on the PlatformDev role
# (see platform_roles.tf DuckLakeEndpointDiscovery statement). No write-path data
# transits SSM -- these parameters hold only the public Function URL strings.
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "ducklake_reader_url" {
  name        = "/agent-platform/ducklake/reader_url"
  type        = "String"
  value       = aws_lambda_function_url.ducklake_reader.function_url
  description = "DuckLake reader Function URL for endpoint discovery (Decision 79 / Decision 81 cl.7)"

  tags = {
    Name    = "ducklake-reader-url"
    Purpose = "T2.19 DuckLake endpoint discovery"
  }
}

resource "aws_ssm_parameter" "ducklake_writer_url" {
  name        = "/agent-platform/ducklake/writer_url"
  type        = "String"
  value       = aws_lambda_function_url.ducklake_writer.function_url
  description = "DuckLake writer Function URL for endpoint discovery (Decision 79 / Decision 81 cl.7)"

  tags = {
    Name    = "ducklake-writer-url"
    Purpose = "T2.19 DuckLake endpoint discovery"
  }
}
