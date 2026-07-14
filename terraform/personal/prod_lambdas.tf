# Prod-class Lambda functions (T2.43 / Decision 125/126): the decoupled_build_pipeline class.
#
# Provisions the three functions that were ABSENT from the personal account (rec-2157/rec-2164):
# agent-platform-scheduled-agent-dispatcher, agent-platform-findings-processor, and
# agent-platform-ops-compaction. Ported from the retired terraform/scheduled_agents.tf (work-account
# root, CD.21) and adapted to the personal-module idiom: var.account_id / data.aws_caller_identity
# interpolation (never a literal, Decision 101), the single agent-platform-data-lake bucket (this
# module has no separate agent-logs bucket -- agents/, findings/, recommendations/, and staging/ are
# all prefixes on aws_s3_bucket.data_lake), the default provider (agent_platform_admin), and a
# PER-FUNCTION execution role + inline policy each (least-privilege, mirroring the ducklake_lambdas.tf
# precedent) rather than the one shared role the retired file used.
#
# ---------------------------------------------------------------------------
# APPLY POSTURE (Decision 35 + 77 + 98): HUMAN-GATED via agent_platform_admin.
# ---------------------------------------------------------------------------
# These resources create NEW IAM roles + inline policies, which trip the Decision-77 deterministic
# guard (scripts/terraform_apply_guard.py, fail-closed on any IAM/trust change). The whole
# terraform/personal apply for this change therefore routes to the MANUAL agent_platform_admin path,
# NOT push-to-main auto-apply.
#
# CODE/INFRA DECOUPLING (Decision 125, environment-taxonomy.md section 5): every aws_lambda_function
# below carries a lifecycle block ignoring source_code_hash changes FROM DAY ONE -- unlike the
# DuckLake class (which coupled first and decoupled later at #544), this class is decoupled from its
# very first apply. Code deploys go via the governed .github/workflows/deploy-prod-lambdas.yml channel
# (T2.43), never terraform.
#
# SCHEDULE STAYS DISABLED (Decision 61/37/116): the dispatcher's EventBridge rule is provisioned with
# state = "DISABLED" and env SCHEDULED_AGENTS_ENABLED = "false". Provisioning these functions does NOT
# re-enable the scheduled agents -- that is a separate, later decision (see AGENTS.md's "Re-enable
# Lambda scheduled agents" runbook). Both scheduled_agent_handler.handler and
# findings_processor_handler.handler degrade gracefully with no live GitHub PAT value or S3 event
# payload (verified against the handler source at plan time), so a smoke invocation of either function
# produces clean, observable JSON output without depending on the schedule being enabled.

locals {
  prod_source_hash           = try(filemd5("${path.module}/../../lambda-packages/data-pipeline.zip"), null)
  ops_compaction_source_hash = try(filemd5("${path.module}/../../lambda-packages/ops-compaction.zip"), null)

  scheduled_agent_dispatcher_function = "agent-platform-scheduled-agent-dispatcher"
  findings_processor_function         = "agent-platform-findings-processor"
  ops_compaction_function             = "agent-platform-ops-compaction"

  # sensitive() keeps this 12-digit ARN out of cleartext terraform plan/show output. It is
  # AWS's OWN publicly-documented Lambda-layer-hosting account (AWS Data Wrangler's managed
  # layer, not this project's account -- Decision 101 is unaffected), but the speculative-plan
  # CI job's redaction self-check fails closed on ANY undelimited 12-digit run regardless of
  # whose account it is, and this literal is unavoidable input knowledge. Marking it sensitive
  # is the HCL-level fix: terraform renders "(sensitive value)" for the affected attribute in
  # every plan/show/apply invocation, not just a one-off workflow-script patch.
  aws_sdk_pandas_layer_arn = sensitive("arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python312:22")
}

# ---------------------------------------------------------------------------
# GitHub PAT secret (dispatcher / findings-processor GitHub Models API auth). Value set out-of-band
# via put-secret-value -- never Terraform-managed (Decision 37 out-of-band precedent, mirrors
# inference_credentials.tf / secrets_manager_brokers.tf). No secret-version resource: key material
# must never enter Terraform state.
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "github_pat" {
  name        = "agent-platform-github-pat" # pragma: allowlist secret -- public Secrets Manager resource name, not a value
  description = "GitHub PAT for the scheduled-agent-dispatcher + findings-processor Lambda functions to call the GitHub Models API (T2.43). Value set out-of-band via put-secret-value; never Terraform-managed (Decision 37)."

  tags = {
    Name    = "Scheduled Agent GitHub PAT"
    Purpose = "T2.43 scheduled-agent-dispatcher / findings-processor GitHub Models API auth"
  }
}

# ---------------------------------------------------------------------------
# NOTE (T2.43 apply-time correction): no shared dependencies layer is attached to the
# dispatcher/findings-processor functions. The full PROD_DEPS-based data-pipeline-deps-layer
# (numpy/pandas/pyarrow/scikit-learn/yfinance/etc., built for the future-state fetch/feature/
# write/discovery handlers) was found at the first real apply to exceed the Lambda 262 MB
# unzipped-layer ceiling (PublishLayerVersion InvalidParameterValueException) -- and these two
# functions don't need any of it regardless (verified against handler source: the only
# third-party import is pyyaml). pyyaml is bundled directly into data-pipeline.zip via
# src/lambdas/data-pipeline/manifest.yaml's pip_packages instead.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CloudWatch log groups (pre-created so each execution role can be scoped to its own ARN).
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "scheduled_agent_dispatcher" {
  name              = "/aws/lambda/${local.scheduled_agent_dispatcher_function}"
  retention_in_days = 14

  tags = {
    Name    = "Scheduled Agent Dispatcher Logs"
    Purpose = "T2.43 scheduled-agent-dispatcher runtime"
  }
}

resource "aws_cloudwatch_log_group" "findings_processor" {
  name              = "/aws/lambda/${local.findings_processor_function}"
  retention_in_days = 14

  tags = {
    Name    = "Findings Processor Logs"
    Purpose = "T2.43 findings-processor runtime"
  }
}

resource "aws_cloudwatch_log_group" "ops_compaction" {
  name              = "/aws/lambda/${local.ops_compaction_function}"
  retention_in_days = 14

  tags = {
    Name    = "Ops Compaction Logs"
    Purpose = "T2.43 ops-compaction runtime"
  }
}

# ---------------------------------------------------------------------------
# Execution role: scheduled-agent-dispatcher. Writes raw findings under agents/, reads the GitHub
# PAT secret to call the GitHub Models API. Reuses data.aws_iam_policy_document.lambda_assume
# (defined once in ducklake_lambdas.tf; a module-global data source, not file-scoped).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "scheduled_agent_dispatcher" {
  name               = local.scheduled_agent_dispatcher_function
  description        = "Execution role for the scheduled-agent-dispatcher Lambda (T2.43)"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "scheduled_agent_dispatcher" {
  name = "ScheduledAgentDispatcherRuntime"
  role = aws_iam_role.scheduled_agent_dispatcher.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.scheduled_agent_dispatcher.arn}:*"]
      },
      {
        Sid      = "GithubPatRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.github_pat.arn]
      },
      {
        Sid      = "S3AgentFindingsWrite"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/agents/*"]
      },
      {
        Sid      = "S3ListAgentsPrefix"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["agents/*"]
          }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Execution role: findings-processor. Reads agents/ raw findings, writes findings/unified.jsonl +
# recommendations/agent-recommendations.jsonl + priority-queue/, reads the GitHub PAT secret.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "findings_processor" {
  name               = local.findings_processor_function
  description        = "Execution role for the findings-processor Lambda (T2.43)"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "findings_processor" {
  name = "FindingsProcessorRuntime"
  role = aws_iam_role.findings_processor.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.findings_processor.arn}:*"]
      },
      {
        Sid      = "GithubPatRead"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.github_pat.arn]
      },
      {
        Sid    = "S3FindingsReadWrite"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/agents/*",
          "${aws_s3_bucket.data_lake.arn}/findings/*",
          "${aws_s3_bucket.data_lake.arn}/recommendations/*",
          "${aws_s3_bucket.data_lake.arn}/priority-queue/*",
        ]
      },
      {
        Sid      = "S3ListFindingsPrefixes"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.data_lake.arn]
        Condition = {
          StringLike = {
            "s3:prefix" = ["agents/*", "findings/*", "recommendations/*", "priority-queue/*"]
          }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Execution role: ops-compaction. Reads + deletes staging/ batches, writes iceberg/ + tmp/ + athena/
# results, Glue table read/schema-evolution, Athena StartQueryExecution (wr.athena.to_iceberg).
# DEPRECATED (T2.26 retirement pending) -- provisioned per this plan's human-confirmed disposition
# regardless (see docs/plans/PLAN-prod-lambda-provision-deploy-channel.yaml Context).
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ops_compaction" {
  name               = local.ops_compaction_function
  description        = "Execution role for the ops-compaction Lambda (T2.43)"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "ops_compaction" {
  name = "OpsCompactionRuntime"
  role = aws_iam_role.ops_compaction.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.ops_compaction.arn}:*"]
      },
      {
        Sid      = "S3StagingReadDelete"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.data_lake.arn}/staging/*"]
      },
      {
        Sid    = "S3IcebergTempAthenaReadWrite"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}/iceberg/*",
          "${aws_s3_bucket.data_lake.arn}/tmp/*",
          "${aws_s3_bucket.data_lake.arn}/athena/*",
        ]
      },
      {
        Sid      = "S3ListDataLake"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.data_lake.arn]
      },
      {
        # wr.athena.to_iceberg / _refresh_view issue StartQueryExecution against the production
        # workgroup; GetQueryExecution/GetQueryResults/GetWorkGroup do not support resource-level
        # scoping for a workgroup-name constraint beyond the StartQueryExecution call itself.
        Sid    = "AthenaCompaction"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetWorkGroup",
        ]
        Resource = "*"
      },
      {
        # wr.catalog.get_table_types (schema-evolution detection) + to_iceberg's own table
        # read/create/update.
        Sid    = "GlueCompaction"
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartitions",
          "glue:CreateTable",
          "glue:UpdateTable",
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:database/${aws_glue_catalog_database.ops.name}",
          "arn:aws:glue:${var.aws_region}:${var.account_id}:table/${aws_glue_catalog_database.ops.name}/*",
        ]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# The three Lambda functions (from S3). source_code_hash try()-guarded; code is updated post-apply
# by the governed .github/workflows/deploy-prod-lambdas.yml channel (T2.43).
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "scheduled_agent_dispatcher" {
  function_name = local.scheduled_agent_dispatcher_function
  description   = "T2.43 scheduled-agent dispatcher (Decision 125/126 decoupled_build_pipeline class). Schedule stays DISABLED (Decision 61/37/116)."
  role          = aws_iam_role.scheduled_agent_dispatcher.arn
  handler       = "src.data.handlers.scheduled_agent_handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = 900 # 15 minutes -- enough for sequential agent execution when eventually enabled
  memory_size   = 512

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/data-pipeline.zip"
  source_code_hash = local.prod_source_hash

  environment {
    variables = {
      GITHUB_PAT_SECRET_ARN    = aws_secretsmanager_secret.github_pat.arn
      S3_LOG_BUCKET            = aws_s3_bucket.data_lake.id
      SCHEDULED_AGENTS_ENABLED = "false"
    }
  }

  depends_on = [
    aws_iam_role_policy.scheduled_agent_dispatcher,
    aws_cloudwatch_log_group.scheduled_agent_dispatcher,
  ]

  # Decision 125 decoupling from day one (see file header): code deploys go via the governed
  # deploy-prod-lambdas.yml channel (T2.43), never terraform.
  lifecycle {
    ignore_changes = [source_code_hash]
  }

  tags = {
    Name    = "Scheduled Agent Dispatcher"
    Purpose = "T2.43 scheduled-agent-dispatcher runtime - schedule disabled"
  }
}

resource "aws_lambda_function" "findings_processor" {
  function_name = local.findings_processor_function
  description   = "T2.43 findings processor (Decision 125/126 decoupled_build_pipeline class). Flagged for Phase-5 retirement (Decision 61)."
  role          = aws_iam_role.findings_processor.arn
  handler       = "src.data.handlers.findings_processor_handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = 300 # 5 minutes -- comparison call + S3 writes
  memory_size   = 256

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/data-pipeline.zip"
  source_code_hash = local.prod_source_hash

  environment {
    variables = {
      GITHUB_PAT_SECRET_ARN = aws_secretsmanager_secret.github_pat.arn
      S3_LOG_BUCKET         = aws_s3_bucket.data_lake.id
    }
  }

  depends_on = [
    aws_iam_role_policy.findings_processor,
    aws_cloudwatch_log_group.findings_processor,
  ]

  lifecycle {
    ignore_changes = [source_code_hash]
  }

  tags = {
    Name    = "Findings Processor"
    Purpose = "T2.43 findings-processor runtime"
  }
}

resource "aws_lambda_function" "ops_compaction" {
  function_name = local.ops_compaction_function
  description   = "T2.43 ops compaction (Decision 125/126 decoupled_build_pipeline class). DEPRECATED -- serves ops_session_log/ops_execution_plans/telemetry staging only; T2.26 retirement pending."
  role          = aws_iam_role.ops_compaction.arn
  handler       = "src.data.handlers.ops_compaction_handler.handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = 300
  memory_size   = 256

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = "lambda-packages/ops-compaction.zip"
  source_code_hash = local.ops_compaction_source_hash

  # Only AWSSDKPandas is needed (provides awswrangler for Iceberg writes). The data-pipeline-deps
  # layer (yfinance/pyyaml) is omitted to keep the combined unzipped size under the 262 MB limit.
  # local.aws_sdk_pandas_layer_arn is sensitive()-wrapped -- see its definition above.
  layers = [local.aws_sdk_pandas_layer_arn]

  environment {
    variables = {
      S3_LOG_BUCKET = aws_s3_bucket.data_lake.id
    }
  }

  depends_on = [
    aws_iam_role_policy.ops_compaction,
    aws_cloudwatch_log_group.ops_compaction,
  ]

  lifecycle {
    ignore_changes = [source_code_hash]
  }

  tags = {
    Name    = "Ops Compaction"
    Purpose = "T2.43 ops-compaction runtime - T2.26 retirement pending"
  }
}

# ---------------------------------------------------------------------------
# EventBridge -- hourly schedule -> dispatcher. Provisioned DISABLED (Decision 61/37/116);
# provisioning this trigger does NOT re-enable the scheduled agents.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "hourly_scheduled_agents" {
  name                = "agent-platform-hourly-scheduled-agents"
  description         = "Invoke scheduled agent dispatcher every hour (T2.43; stays DISABLED -- Decision 61/37/116)"
  schedule_expression = "cron(0 * * * ? *)"
  state               = "DISABLED"

  tags = {
    Name = "Hourly Scheduled Agents"
  }
}

resource "aws_cloudwatch_event_target" "hourly_scheduled_agents_dispatcher" {
  rule      = aws_cloudwatch_event_rule.hourly_scheduled_agents.name
  target_id = "scheduled-agent-dispatcher"
  arn       = aws_lambda_function.scheduled_agent_dispatcher.arn
}

resource "aws_lambda_permission" "eventbridge_invoke_dispatcher" {
  statement_id  = "AllowEventBridgeInvokeDispatcher"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduled_agent_dispatcher.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_scheduled_agents.arn
}

# ---------------------------------------------------------------------------
# S3 event notifications -- agent findings -> findings-processor; staging batches -> ops-compaction.
#
# GOTCHA: aws_s3_bucket_notification is a SINGLETON per bucket -- only ONE such resource may target
# aws_s3_bucket.data_lake in this module, or one apply will silently clobber the other's
# configuration. Both triggers are declared inside this single resource; a future addition of a
# third data_lake trigger must extend THIS resource, not add a sibling aws_s3_bucket_notification.
# ---------------------------------------------------------------------------

resource "aws_lambda_permission" "s3_invoke_findings_processor" {
  statement_id  = "AllowS3InvokeFindingsProcessor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.findings_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.data_lake.arn
}

resource "aws_lambda_permission" "s3_invoke_ops_compaction" {
  statement_id  = "AllowS3InvokeOpsCompaction"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ops_compaction.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.data_lake.arn
}

resource "aws_s3_bucket_notification" "data_lake_prod_triggers" {
  bucket = aws_s3_bucket.data_lake.id

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

# ---------------------------------------------------------------------------
# Outputs -- consumed by the governed deploy workflow / operator verification (VP steps 8-11).
# ---------------------------------------------------------------------------

output "scheduled_agent_dispatcher_function_name" {
  description = "scheduled-agent-dispatcher Lambda function name (deploy-prod-lambdas.yml target)."
  value       = aws_lambda_function.scheduled_agent_dispatcher.function_name
}

output "findings_processor_function_name" {
  description = "findings-processor Lambda function name (deploy-prod-lambdas.yml target)."
  value       = aws_lambda_function.findings_processor.function_name
}

output "ops_compaction_function_name" {
  description = "ops-compaction Lambda function name (deploy-prod-lambdas.yml target)."
  value       = aws_lambda_function.ops_compaction.function_name
}
