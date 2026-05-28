# Data Pipeline Infrastructure
# Step Functions state machine + EventBridge schedule + Lambda functions
# Orchestrates: Fetch OHLCV → Compute Features → Write to Iceberg → (optional) Discovery
#
# Lambda Deployment: Zip-based (no Docker required)
#   Build with: scripts/build_lambda.ps1
#   Uploads zip to S3 data lake bucket under lambda-packages/

# ─────────────────────────────────────────────────────────────────────
# S3 object for Lambda deployment package
# Built by scripts/build_lambda.ps1 → uploaded to data lake bucket
# ─────────────────────────────────────────────────────────────────────

locals {
  lambda_s3_key = "lambda-packages/data-pipeline.zip"
  # Use try() to provide fallback hash if zip file doesn't exist (e.g., in CI environment)
  # In CI, terraform validate runs without built artifacts; local CI would have zips
  lambda_source_hash = try(
    filemd5("${path.module}/../lambda-packages/data-pipeline.zip"),
    md5(file("${path.module}/data_pipeline.tf"))
  )

  # AWS-managed layer: pandas, numpy, pyarrow, boto3, s3fs, awswrangler
  # Source: https://aws-sdk-pandas.readthedocs.io/en/stable/layers.html
  aws_sdk_pandas_layer_arn = "arn:aws:lambda:${var.aws_region}:336392948345:layer:AWSSDKPandas-Python312:22"
}

# Small extras layer: dependencies NOT in AWSSDKPandas (yfinance, pyyaml)
# Built with: pip install --platform manylinux2014_x86_64 --only-binary=:all:
# Pre-compiled Linux wheels from PyPI — no Docker required
resource "aws_lambda_layer_version" "data_pipeline_extras" {
  layer_name          = "${var.project_name}-data-pipeline-extras"
  s3_bucket           = aws_s3_bucket.data_lake.id
  s3_key              = "lambda-packages/data-pipeline-extras-layer.zip"
  compatible_runtimes = ["python3.12"]
  description         = "Extra dependencies not in AWSSDKPandas (yfinance, pyyaml)"
  # Use try() to provide fallback hash if zip file doesn't exist (e.g., in CI environment)
  source_code_hash = try(
    filemd5("${path.module}/../lambda-packages/data-pipeline-extras-layer.zip"),
    md5(file("${path.module}/data_pipeline.tf"))
  )
}

# ─────────────────────────────────────────────────────────────────────
# IAM Role for Lambda functions
# ─────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "data_pipeline_lambda" {
  name = "${var.project_name}-data-pipeline-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name  = "Data Pipeline Lambda Role"
    Phase = "Phase_1_DataPipeline"
  }
}

# Lambda basic execution (CloudWatch Logs)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.data_pipeline_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# S3 access for data lake (read/write staging + Iceberg data)
resource "aws_iam_role_policy" "lambda_s3_access" {
  name = "data-pipeline-s3-access"
  role = aws_iam_role.data_pipeline_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation"
        ]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}",
          "${aws_s3_bucket.data_lake.arn}/*",
          "${aws_s3_bucket.formulas_discovery.arn}",
          "${aws_s3_bucket.formulas_discovery.arn}/*"
        ]
      }
    ]
  })
}

# Glue catalog access (for PyIceberg table operations)
resource "aws_iam_role_policy" "lambda_glue_access" {
  name = "data-pipeline-glue-access"
  role = aws_iam_role.data_pipeline_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:CreateTable",
          "glue:DeleteTable",
          "glue:UpdateTable",
          "glue:GetPartitions"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:*:catalog",
          "arn:aws:glue:${var.aws_region}:*:database/${aws_glue_catalog_database.trading_db.name}",
          "arn:aws:glue:${var.aws_region}:*:table/${aws_glue_catalog_database.trading_db.name}/*"
        ]
      }
    ]
  })
}

# Athena access (for write handler via awswrangler + discovery handler)
resource "aws_iam_role_policy" "lambda_athena_access" {
  name = "data-pipeline-athena-access"
  role = aws_iam_role.data_pipeline_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetWorkGroup"
        ]
        Resource = "*"
      }
    ]
  })
}

# ─────────────────────────────────────────────────────────────────────
# CloudWatch Log Groups for Lambda functions
# ─────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "fetch_market_data" {
  name              = "/aws/lambda/${var.project_name}-fetch-market-data"
  retention_in_days = 30

  tags = {
    Name  = "Fetch Market Data Lambda Logs"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_cloudwatch_log_group" "compute_features" {
  name              = "/aws/lambda/${var.project_name}-compute-features"
  retention_in_days = 30

  tags = {
    Name  = "Compute Features Lambda Logs"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_cloudwatch_log_group" "write_to_iceberg" {
  name              = "/aws/lambda/${var.project_name}-write-to-iceberg"
  retention_in_days = 30

  tags = {
    Name  = "Write To Iceberg Lambda Logs"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_cloudwatch_log_group" "trigger_discovery" {
  name              = "/aws/lambda/${var.project_name}-trigger-discovery"
  retention_in_days = 30

  tags = {
    Name  = "Trigger Discovery Lambda Logs"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_cloudwatch_log_group" "table_maintenance" {
  name              = "/aws/lambda/${var.project_name}-table-maintenance"
  retention_in_days = 30

  tags = {
    Name  = "Table Maintenance Lambda Logs"
    Phase = "Phase_1_DataPipeline"
  }
}

# ─────────────────────────────────────────────────────────────────────
# Lambda Functions (one per Step Functions state)
# ─────────────────────────────────────────────────────────────────────

resource "aws_lambda_function" "fetch_market_data" {
  function_name = "${var.project_name}-fetch-market-data"
  role          = aws_iam_role.data_pipeline_lambda.arn
  handler       = "src.data.handlers.fetch_handler.handler"
  runtime       = "python3.12"
  timeout       = 900 # 15 minutes
  memory_size   = 1024

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = local.lambda_s3_key
  source_code_hash = local.lambda_source_hash

  layers = [
    local.aws_sdk_pandas_layer_arn,
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      S3_DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.id
      TRADING_CONFIG      = "config/config.company.yaml"
      TRADING_ENVIRONMENT = "company"
    }
  }

  depends_on = [aws_cloudwatch_log_group.fetch_market_data]

  tags = {
    Name  = "Fetch Market Data"
    Phase = "Phase_1_DataPipeline"
    Step  = "1_Fetch"
  }
}

resource "aws_lambda_function" "compute_features" {
  function_name = "${var.project_name}-compute-features"
  role          = aws_iam_role.data_pipeline_lambda.arn
  handler       = "src.data.handlers.feature_handler.handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 2048 # Feature computation is memory-intensive

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = local.lambda_s3_key
  source_code_hash = local.lambda_source_hash

  layers = [
    local.aws_sdk_pandas_layer_arn,
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      S3_DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.id
      TRADING_CONFIG      = "config/config.company.yaml"
      TRADING_ENVIRONMENT = "company"
    }
  }

  depends_on = [aws_cloudwatch_log_group.compute_features]

  tags = {
    Name  = "Compute Features"
    Phase = "Phase_1_DataPipeline"
    Step  = "2_Features"
  }
}

resource "aws_lambda_function" "write_to_iceberg" {
  function_name = "${var.project_name}-write-to-iceberg"
  role          = aws_iam_role.data_pipeline_lambda.arn
  handler       = "src.data.handlers.write_handler.handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 1024

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = local.lambda_s3_key
  source_code_hash = local.lambda_source_hash

  layers = [
    local.aws_sdk_pandas_layer_arn,
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      S3_DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.id
      ATHENA_WORKGROUP    = aws_athena_workgroup.lab.name
      TRADING_CONFIG      = "config/config.company.yaml"
      TRADING_ENVIRONMENT = "company"
    }
  }

  depends_on = [aws_cloudwatch_log_group.write_to_iceberg]

  tags = {
    Name  = "Write To Iceberg"
    Phase = "Phase_1_DataPipeline"
    Step  = "3_Write"
  }
}

resource "aws_lambda_function" "trigger_discovery" {
  function_name = "${var.project_name}-trigger-discovery"
  role          = aws_iam_role.data_pipeline_lambda.arn
  handler       = "src.data.handlers.discovery_handler.handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 2048 # PySR needs memory

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = local.lambda_s3_key
  source_code_hash = local.lambda_source_hash

  layers = [
    local.aws_sdk_pandas_layer_arn,
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      S3_DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.id
      TRADING_CONFIG      = "config/config.company.yaml"
      TRADING_ENVIRONMENT = "company"
    }
  }

  depends_on = [aws_cloudwatch_log_group.trigger_discovery]

  tags = {
    Name  = "Trigger Discovery"
    Phase = "Phase_1_DataPipeline"
    Step  = "4_Discovery"
  }
}

resource "aws_lambda_function" "table_maintenance" {
  function_name = "${var.project_name}-table-maintenance"
  role          = aws_iam_role.data_pipeline_lambda.arn
  handler       = "src.data.handlers.maintenance_handler.handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 512

  s3_bucket        = aws_s3_bucket.data_lake.id
  s3_key           = local.lambda_s3_key
  source_code_hash = local.lambda_source_hash

  layers = [
    local.aws_sdk_pandas_layer_arn,
    aws_lambda_layer_version.data_pipeline_extras.arn,
  ]

  environment {
    variables = {
      S3_DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.id
      TRADING_CONFIG      = "config/config.company.yaml"
      TRADING_ENVIRONMENT = "company"
    }
  }

  depends_on = [aws_cloudwatch_log_group.table_maintenance]

  tags = {
    Name  = "Table Maintenance"
    Phase = "Phase_1_DataPipeline"
    Step  = "3b_Maintenance"
  }
}

# ─────────────────────────────────────────────────────────────────────
# Step Functions State Machine
# ─────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "step_functions_execution" {
  name = "${var.project_name}-data-pipeline-sfn"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name  = "Data Pipeline Step Functions Role"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  name = "sfn-invoke-lambda"
  role = aws_iam_role.step_functions_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [
          aws_lambda_function.fetch_market_data.arn,
          aws_lambda_function.compute_features.arn,
          aws_lambda_function.write_to_iceberg.arn,
          aws_lambda_function.table_maintenance.arn,
          aws_lambda_function.trigger_discovery.arn,
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "data_pipeline_sfn" {
  name              = "/aws/states/${var.project_name}-data-pipeline"
  retention_in_days = 30

  tags = {
    Name  = "Data Pipeline Step Functions Logs"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_sfn_state_machine" "data_pipeline" {
  name     = "${var.project_name}-data-pipeline"
  role_arn = aws_iam_role.step_functions_execution.arn

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.data_pipeline_sfn.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  definition = jsonencode({
    Comment = "Market data ingestion pipeline: Fetch → Features → Iceberg → Discovery"
    StartAt = "FetchMarketData"
    States = {

      # ── Step 1: Fetch raw OHLCV from yfinance ──────────────────────
      FetchMarketData = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.fetch_market_data.arn
          "Payload.$"  = "$"
        }
        ResultPath = "$.fetchResult"
        ResultSelector = {
          "date.$"            = "$.Payload.date"
          "raw_s3_key.$"      = "$.Payload.raw_s3_key"
          "symbols_fetched.$" = "$.Payload.symbols_fetched"
          "is_empty.$"        = "$.Payload.is_empty"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.AWSLambdaException"]
            IntervalSeconds = 30
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "HandleError"
            ResultPath  = "$.error"
          }
        ]
        Next = "CheckFetchResult"
      }

      # ── Check if fetch returned data ───────────────────────────────
      CheckFetchResult = {
        Type = "Choice"
        Choices = [
          {
            Variable      = "$.fetchResult.is_empty"
            BooleanEquals = true
            Next          = "NoDataAvailable"
          }
        ]
        Default = "ComputeFeatures"
      }

      # ── No data (weekend/holiday) — end gracefully ─────────────────
      NoDataAvailable = {
        Type    = "Succeed"
        Comment = "No market data available (weekend/holiday)"
      }

      # ── Step 2: Compute technical indicators, sentiment, fundamentals
      ComputeFeatures = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.compute_features.arn
          "Payload.$"  = "$.fetchResult"
        }
        ResultPath = "$.featureResult"
        ResultSelector = {
          "date.$"              = "$.Payload.date"
          "enriched_s3_key.$"   = "$.Payload.enriched_s3_key"
          "features_computed.$" = "$.Payload.features_computed"
          "is_empty.$"          = "$.Payload.is_empty"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.AWSLambdaException"]
            IntervalSeconds = 30
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "HandleError"
            ResultPath  = "$.error"
          }
        ]
        Next = "WriteToIceberg"
      }

      # ── Step 3: Write enriched data to Iceberg table ───────────────
      WriteToIceberg = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.write_to_iceberg.arn
          "Payload.$"  = "$.featureResult"
        }
        ResultPath = "$.writeResult"
        ResultSelector = {
          "date.$"         = "$.Payload.date"
          "rows_written.$" = "$.Payload.rows_written"
          "source.$"       = "$.Payload.source"
          "is_empty.$"     = "$.Payload.is_empty"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.AWSLambdaException"]
            IntervalSeconds = 30
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "HandleError"
            ResultPath  = "$.error"
          }
        ]
        Next = "TableMaintenance"
      }

      # ── Step 3b: Iceberg table maintenance (OPTIMIZE + VACUUM) ────
      TableMaintenance = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.table_maintenance.arn
          "Payload.$"  = "$.writeResult"
        }
        ResultPath = "$.maintenanceResult"
        ResultSelector = {
          "date.$"            = "$.Payload.date"
          "optimize_status.$" = "$.Payload.optimize_status"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.AWSLambdaException"]
            IntervalSeconds = 30
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "CheckDiscoveryEnabled"
            ResultPath  = "$.maintenanceError"
            Comment     = "Maintenance failures are non-fatal — continue to discovery"
          }
        ]
        Next = "CheckDiscoveryEnabled"
      }

      # ── Choice: should we run formula discovery? ───────────────────
      CheckDiscoveryEnabled = {
        Type    = "Choice"
        Comment = "Gate discovery behind a config flag — disabled by default"
        Choices = [
          {
            Variable      = "$.discovery_enabled"
            BooleanEquals = true
            Next          = "TriggerDiscovery"
          }
        ]
        Default = "PipelineComplete"
      }

      # ── Step 4 (optional): Run PySR formula discovery ──────────────
      TriggerDiscovery = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.trigger_discovery.arn
          "Payload.$"  = "$.writeResult"
        }
        ResultPath = "$.discoveryResult"
        ResultSelector = {
          "date.$"                = "$.Payload.date"
          "discovery_triggered.$" = "$.Payload.discovery_triggered"
          "formulas_found.$"      = "$.Payload.formulas_found"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.AWSLambdaException"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "HandleError"
            ResultPath  = "$.error"
          }
        ]
        Next = "PipelineComplete"
      }

      # ── Success ────────────────────────────────────────────────────
      PipelineComplete = {
        Type = "Succeed"
      }

      # ── Error handler ─────────────────────────────────────────────
      HandleError = {
        Type  = "Fail"
        Error = "DataPipelineError"
        Cause = "A step in the data pipeline failed. Check CloudWatch logs for details."
      }
    }
  })

  tags = {
    Name  = "Market Data Pipeline"
    Phase = "Phase_1_DataPipeline"
  }
}

# ─────────────────────────────────────────────────────────────────────
# EventBridge Schedule (daily at 6pm UTC, weekdays)
# ─────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "eventbridge_sfn" {
  name = "${var.project_name}-eventbridge-sfn"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name  = "EventBridge to Step Functions Role"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_iam_role_policy" "eventbridge_start_sfn" {
  name = "start-data-pipeline"
  role = aws_iam_role.eventbridge_sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = aws_sfn_state_machine.data_pipeline.arn
      }
    ]
  })
}

resource "aws_cloudwatch_event_rule" "daily_data_pipeline" {
  name                = "${var.project_name}-daily-data-pipeline"
  description         = "Trigger market data pipeline at 6pm UTC on weekdays (90 min after LSE close)"
  schedule_expression = "cron(0 18 ? * MON-FRI *)"
  state               = var.data_pipeline_schedule_enabled ? "ENABLED" : "DISABLED"

  tags = {
    Name  = "Daily Data Pipeline Schedule"
    Phase = "Phase_1_DataPipeline"
  }
}

resource "aws_cloudwatch_event_target" "data_pipeline" {
  rule      = aws_cloudwatch_event_rule.daily_data_pipeline.name
  target_id = "DataPipelineExecution"
  arn       = aws_sfn_state_machine.data_pipeline.arn
  role_arn  = aws_iam_role.eventbridge_sfn.arn

  input = jsonencode({
    discovery_enabled = false # Set to true to chain formula discovery
    # date is intentionally omitted — fetch_handler defaults to today's date
    # when the key is absent.  Pass an ISO date string only to reprocess a
    # specific day (e.g. manual execution via start-execution).
  })
}

# ─────────────────────────────────────────────────────────────────────
# CloudWatch Alarm — alert on pipeline failures
# ─────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "pipeline_failures" {
  alarm_name          = "${var.project_name}-data-pipeline-failures"
  alarm_description   = "Alert when the data pipeline Step Functions execution fails"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 86400 # 24 hours
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.data_pipeline.arn
  }

  alarm_actions = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []

  tags = {
    Name  = "Data Pipeline Failure Alarm"
    Phase = "Phase_1_DataPipeline"
  }
}

# ─────────────────────────────────────────────────────────────────────
# IAM Policy — GitHub Actions cron agents: agent-logs S3 access
#
# Note: No GitHub Actions OIDC role exists in this Terraform configuration yet.
# When the cron workflow is implemented, create an OIDC role and attach this
# policy. For now, the policy is created but not attached to any role.
# ─────────────────────────────────────────────────────────────────────

resource "aws_iam_policy" "agent_logs_s3_access" {
  name        = "${var.project_name}-agent-logs-s3-access"
  description = "Grants cron agents read/write access to the agent-logs S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
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
      }
    ]
  })
}
