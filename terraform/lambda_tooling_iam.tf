# ============================================================================
# Platform IAM Roles -- Pattern B agent-auth
#
# Two-role model per CD.10: PlatformDev (daily ops) and PlatformAdmin
# (T2.2 import-mode + emergency operations). Both are assumed by
# agent-service-account via static-key + chained AssumeRole with ExternalId.
#
# IMPORT NOTE (T2.1): Resources below are declared but NOT applied in this plan.
# Per CD.6 (personal-account rebuild-not-migrate), T2.1 is the canonical apply
# moment. The console-created roles MUST be imported rather than re-created:
#   terraform import 'aws_iam_role.platform_dev' 'PlatformDev'
#   terraform import 'aws_iam_role.platform_admin' 'PlatformAdmin'
# ============================================================================

# ---------------------------------------------------------------------------
# Lambda execution role (unchanged)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "platform_lambda_execution" {
  provider = aws.platform
  name     = "agent-platform-lambda-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "platform_lambda_logs" {
  provider = aws.platform
  name     = "agent-platform-lambda-logs"
  role     = aws_iam_role.platform_lambda_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.platform_region}:${var.platform_account_id}:log-group:/aws/lambda/agent-platform-*:*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "platform_lambda_dynamodb" {
  provider = aws.platform
  name     = "agent-platform-lambda-dynamodb"
  role     = aws_iam_role.platform_lambda_execution.id

  # The agent-platform-counters table does not exist as a Terraform resource in this
  # plan (T2.1 creates it). The ARN is referenced by name; terraform validate passes
  # regardless. The actual policy takes effect at T2.1 apply time.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ]
        Resource = "arn:aws:dynamodb:${var.platform_region}:${var.platform_account_id}:table/agent-platform-counters"
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# PlatformDev -- daily agent ops role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "platform_dev" {
  provider             = aws.platform
  name                 = "PlatformDev"
  max_session_duration = 3600
  description          = "Daily agent ops: Bedrock invoke, S3 read/write, Athena query, DynamoDB ops, Lambda invoke (non-admin)"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::${var.platform_account_id}:user/${aws_iam_user.agent_service_account.name}"
        }
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.platform_dev_external_id
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "platform_dev_daily_ops" {
  provider = aws.platform
  name     = "DailyOps"
  role     = aws_iam_role.platform_dev.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "LambdaInvoke"
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunctionUrl", "lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.platform_region}:${var.platform_account_id}:function:agent-platform-*"
      },
      {
        Sid    = "S3PlatformBuckets"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::bblake-*",
          "arn:aws:s3:::bblake-*/*",
        ]
      },
      {
        Sid    = "AthenaQuery"
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
        ]
        Resource = "arn:aws:athena:${var.platform_region}:${var.platform_account_id}:workgroup/agent-platform-production"
      },
      {
        Sid    = "DynamoDBOps"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
        ]
        Resource = "arn:aws:dynamodb:${var.platform_region}:${var.platform_account_id}:table/agent-platform-*"
      },
      {
        Sid      = "GlueReadForAthena"
        Effect   = "Allow"
        Action   = ["glue:GetTable", "glue:GetPartitions", "glue:GetDatabase"]
        Resource = "*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# PlatformAdmin -- T2.2 import-mode + emergency operations role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "platform_admin" {
  provider             = aws.platform
  name                 = "PlatformAdmin"
  max_session_duration = 3600 # AWS IAM minimum is 3600; limit actual sessions to 30min via duration_seconds in ~/.aws/config
  description          = "Admin ops: iam:* for T2.2 import, admin Lambda management, emergency overrides"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          AWS = "arn:aws:iam::${var.platform_account_id}:user/${aws_iam_user.agent_service_account.name}"
        }
        Condition = {
          StringEquals = {
            "sts:ExternalId" = var.platform_admin_external_id
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "platform_admin_ops" {
  provider = aws.platform
  name     = "AdminOps"
  role     = aws_iam_role.platform_admin.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "IAMFull"
        Effect   = "Allow"
        Action   = "iam:*"
        Resource = "*"
      },
      {
        Sid    = "LambdaAdminManagement"
        Effect = "Allow"
        Action = [
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:InvokeFunctionUrl",
          "lambda:InvokeFunction",
          "lambda:GetFunction",
          "lambda:ListFunctions",
        ]
        Resource = "*"
      },
      {
        Sid    = "SecretsManagerAdmin"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:CreateSecret",
          "secretsmanager:DescribeSecret",
        ]
        Resource = "*"
      },
    ]
  })
}
