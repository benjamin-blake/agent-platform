# Scheduled Agents Infrastructure
# Lambda + EventBridge + S3 event notification for autonomous code-analysis agents.
# Replaces the GitHub Actions OIDC approach (Decision 36 superseded by Decision 37).
# See docs/DECISIONS.md Decision 37 for rationale.

# ─────────────────────────────────────────────────────────────────────
# Locals
# ─────────────────────────────────────────────────────────────────────

locals {
  # Scheduled-agents Lambda zip (same build as data-pipeline for now;
  # both handlers live in the same package)
  agent_lambda_source_hash = try(
    filemd5("${path.module}/../lambda-packages/data-pipeline.zip"),
    md5(file("${path.module}/scheduled_agents.tf"))
  )

  # ops_compaction uses a separate minimal zip (no Copilot SDK) to stay
  # under the 262 MB Lambda combined-with-layers size limit imposed by
  # the attached AWSSDKPandas layer (~128 MB unzipped).
  ops_compaction_source_hash = try(
    filemd5("${path.module}/../lambda-packages/ops-compaction.zip"),
    md5(file("${path.module}/scheduled_agents.tf"))
  )
}

# ─────────────────────────────────────────────────────────────────────
# Secrets Manager — GitHub PAT
# The secret value must be set manually after terraform apply:
#   aws secretsmanager put-secret-value \
#     --secret-id agent-platform-github-pat \
#     --secret-string "ghp_YOUR_PAT_HERE" \
#     --profile company-aws-profile
# ─────────────────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "github_pat" {
  name        = "${var.project_name}-github-pat"
  description = "GitHub PAT for scheduled agents to call GitHub Models API"

  tags = {
    Project = var.project_name
    Purpose = "GitHub Models API authentication for scheduled agents"
  }
}

# Placeholder version — the actual PAT value is set manually.
resource "aws_secretsmanager_secret_version" "github_pat_placeholder" {
  secret_id     = aws_secretsmanager_secret.github_pat.id
  secret_string = "PLACEHOLDER_SET_MANUALLY" # pragma: allowlist secret

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# ─────────────────────────────────────────────────────────────────────
# IAM Role — Scheduled agent Lambda
# ─────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "scheduled_agent_lambda" {
  name        = "${var.project_name}-scheduled-agent-lambda"
  description = "Execution role for scheduled-agent Lambda functions"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project = var.project_name
    Purpose = "Scheduled agent dispatcher and findings processor Lambdas"
  }
}

resource "aws_iam_policy" "scheduled_agent_lambda" {
  name        = "${var.project_name}-scheduled-agent-lambda"
  description = "Permissions for scheduled-agent Lambda functions"

  # Bedrock IAM removed (Decision 49 -- Copilot SDK uses GitHub PAT, not IAM).
  # Retained: S3, Secrets Manager, CloudWatch Logs.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3AgentLogs"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.agent_logs.arn,
          "${aws_s3_bucket.agent_logs.arn}/*"
        ]
      },
      {
        Sid    = "SecretsManagerGithubPat"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.github_pat.arn,
        ]
      },
      {
        Sid      = "S3DeleteObject"
        Effect   = "Allow"
        Action   = ["s3:DeleteObject"]
        Resource = "${aws_s3_bucket.agent_logs.arn}/*"
      },
      {
        Sid    = "S3DataLakeAthenaResults"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:GetBucketLocation",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/athena/*"
        ]
      },
      {
        Sid    = "AthenaCompaction"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults"
        ]
        Resource = "*"
      },
      {
        Sid    = "GlueCompaction"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartitions"
        ]
        Resource = "arn:aws:glue:${var.aws_region}:*:*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.project_name}-scheduled-agent*",
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.project_name}-ops-compaction*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "scheduled_agent_lambda" {
  role       = aws_iam_role.scheduled_agent_lambda.name
  policy_arn = aws_iam_policy.scheduled_agent_lambda.arn
}

# ─────────────────────────────────────────────────────────────────────
# CloudWatch Log Groups
# ─────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "scheduled_agent_dispatcher" {
  name              = "/aws/lambda/${var.project_name}-scheduled-agent-dispatcher"
  retention_in_days = 14

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_log_group" "findings_processor" {
  name              = "/aws/lambda/${var.project_name}-findings-processor"
  retention_in_days = 14

  tags = {
    Project = var.project_name
  }
}

# ─────────────────────────────────────────────────────────────────────
# Lambda Functions
# ─────────────────────────────────────────────────────────────────────

resource "aws_lambda_function" "scheduled_agent_dispatcher" {
  function_name = "${var.project_name}-scheduled-agent-dispatcher"
  role          = aws_iam_role.scheduled_agent_lambda.arn
  handler       = "src.data.handlers.scheduled_agent_handler.handler"
  runtime       = "python3.12"
  timeout       = 900 # 15 minutes — enough for sequential agent execution
  memory_size   = 512

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/data-pipeline.zip"
  source_code_hash = local.agent_lambda_source_hash

  layers = [
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      GITHUB_PAT_SECRET_ARN    = aws_secretsmanager_secret.github_pat.arn
      S3_LOG_BUCKET            = aws_s3_bucket.agent_logs.id
      SCHEDULED_AGENTS_ENABLED = "false"
    }
  }

  depends_on = [aws_cloudwatch_log_group.scheduled_agent_dispatcher]

  tags = {
    Project = var.project_name
    Purpose = "Scheduled agent dispatcher - runs due agents via GitHub Models API"
  }
}

resource "aws_lambda_function" "findings_processor" {
  function_name = "${var.project_name}-findings-processor"
  role          = aws_iam_role.scheduled_agent_lambda.arn
  handler       = "src.data.handlers.findings_processor_handler.handler"
  runtime       = "python3.12"
  timeout       = 300 # 5 minutes — comparison call + S3 writes
  memory_size   = 256

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/data-pipeline.zip"
  source_code_hash = local.agent_lambda_source_hash

  layers = [
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      GITHUB_PAT_SECRET_ARN = aws_secretsmanager_secret.github_pat.arn
      S3_LOG_BUCKET         = aws_s3_bucket.agent_logs.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.findings_processor]

  tags = {
    Project = var.project_name
    Purpose = "Findings processor - unions findings and generates recommendations"
  }
}

# ─────────────────────────────────────────────────────────────────────
# EventBridge — hourly schedule → dispatcher
# ─────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "hourly_agents" {
  name                = "${var.project_name}-hourly-scheduled-agents"
  description         = "Invoke scheduled agent dispatcher every hour"
  schedule_expression = "cron(0 * * * ? *)"
  state               = "DISABLED"

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_event_target" "hourly_agents_dispatcher" {
  rule      = aws_cloudwatch_event_rule.hourly_agents.name
  target_id = "scheduled-agent-dispatcher"
  arn       = aws_lambda_function.scheduled_agent_dispatcher.arn
}

resource "aws_lambda_permission" "eventbridge_invoke_dispatcher" {
  statement_id  = "AllowEventBridgeInvokeDispatcher"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduled_agent_dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_agents.arn
}

# ─────────────────────────────────────────────────────────────────────
# S3 Event Notification — agent findings → findings processor
# Triggers findings_processor when a new findings file is written
# under the agents/ prefix.
# ─────────────────────────────────────────────────────────────────────

resource "aws_lambda_permission" "s3_invoke_findings_processor" {
  statement_id  = "AllowS3InvokeFindingsProcessor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.findings_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.agent_logs.arn
}

resource "aws_cloudwatch_log_group" "ops_compaction" {
  name              = "/aws/lambda/${var.project_name}-ops-compaction"
  retention_in_days = 14

  tags = {
    Project = var.project_name
    Name    = "${var.project_name}-ops-compaction"
  }
}

resource "aws_lambda_function" "ops_compaction" {
  function_name = "${var.project_name}-ops-compaction"
  role          = aws_iam_role.scheduled_agent_lambda.arn
  handler       = "src.data.handlers.ops_compaction_handler.handler"
  runtime       = "python3.12"
  timeout       = 300
  memory_size   = 256

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ops-compaction.zip"
  source_code_hash = local.ops_compaction_source_hash

  # Only AWSSDKPandas is needed (provides awswrangler for Iceberg writes).
  # data_pipeline_extras (yfinance/pyyaml) is omitted to keep the combined
  # unzipped size under the 262 MB Lambda limit.
  layers = [
    "arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python312:22",
  ]

  environment {
    variables = {
      S3_LOG_BUCKET = aws_s3_bucket.agent_logs.id
    }
  }

  depends_on = [aws_cloudwatch_log_group.ops_compaction]

  tags = {
    Project = var.project_name
    Purpose = "Ops compaction - flushes staging JSONL into Iceberg ops tables"
  }
}

resource "aws_lambda_permission" "s3_invoke_ops_compaction" {
  statement_id  = "AllowS3InvokeOpsCompaction"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ops_compaction.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.agent_logs.arn
}

resource "aws_s3_bucket_notification" "agent_findings" {
  bucket = aws_s3_bucket.agent_logs.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.findings_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "agents/"
    filter_suffix       = ".jsonl"
  }

  lambda_function {
    lambda_function_arn = aws_lambda_function.ops_compaction.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "staging/"
    filter_suffix       = ".jsonl"
  }

  depends_on = [
    aws_lambda_permission.s3_invoke_findings_processor,
    aws_lambda_permission.s3_invoke_ops_compaction,
  ]
}

# ─────────────────────────────────────────────────────────────────────
# EventBridge -- weekly rec-curator agent
# State is DISABLED until rec-curator is added to the Lambda package
# ─────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "rec_curator_weekly" {
  name                = "${var.project_name}-rec-curator-weekly"
  description         = "Weekly rec-curator agent - prioritises recommendation backlog"
  schedule_expression = "cron(0 8 ? * MON *)"
  state               = "DISABLED"

  tags = {
    Project = var.project_name
    Purpose = "rec-curator weekly trigger"
  }
}

resource "aws_cloudwatch_event_target" "rec_curator_weekly" {
  rule      = aws_cloudwatch_event_rule.rec_curator_weekly.name
  target_id = "rec-curator-dispatcher"
  arn       = aws_lambda_function.scheduled_agent_dispatcher.arn
  input     = jsonencode({ agent_name = "rec-curator" })
}

resource "aws_lambda_permission" "allow_eventbridge_rec_curator" {
  statement_id  = "AllowEventBridgeInvokeRecCurator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduled_agent_dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rec_curator_weekly.arn
}
