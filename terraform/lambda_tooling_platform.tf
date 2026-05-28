# ============================================================================
# Platform Lambda Tooling Surface
#
# Targets the personal AWS account (REDACTED-PERSONAL-ACCOUNT) via the aws.platform provider
# alias. These resources are validate-only per this plan -- no terraform apply
# runs until T2.1 lifts the Decision 67 Lambda freeze.
#
# Resource naming follows INTENT v5 Part 3: agent-platform-{purpose}.
# Lambda names (with hyphens) match the CD.10 canonical contract set exactly.
#
# PREREQUISITE (T2.1 implementing plan): before running `terraform plan`, create
# the archive output directory: `mkdir -p build/lambdas` from the repo root.
# The `build/` directory is gitignored; the six archive_file data sources will
# error at plan time if it is absent (validate passes because data sources are
# not executed during validate).
# ============================================================================

# ---------------------------------------------------------------------------
# Source archives
# ---------------------------------------------------------------------------

data "archive_file" "platform_log_rec" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas/log_rec/"
  output_path = "${path.module}/../build/lambdas/platform_log_rec.zip"
}

data "archive_file" "platform_log_decision" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas/log_decision/"
  output_path = "${path.module}/../build/lambdas/platform_log_decision.zip"
}

data "archive_file" "platform_query" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas/query/"
  output_path = "${path.module}/../build/lambdas/platform_query.zip"
}

data "archive_file" "platform_update_rec" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas/update_rec/"
  output_path = "${path.module}/../build/lambdas/platform_update_rec.zip"
}

data "archive_file" "platform_list_tools" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas/list_tools/"
  output_path = "${path.module}/../build/lambdas/platform_list_tools.zip"
}

data "archive_file" "platform_maintenance" {
  type        = "zip"
  source_dir  = "${path.module}/../src/lambdas/maintenance/"
  output_path = "${path.module}/../build/lambdas/platform_maintenance.zip"
}

# ---------------------------------------------------------------------------
# Lambda functions
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "log_rec" {
  provider         = aws.platform
  function_name    = "agent-platform-log-rec"
  runtime          = "python3.12"
  handler          = "handler.handler"
  role             = aws_iam_role.platform_lambda_execution.arn
  filename         = data.archive_file.platform_log_rec.output_path
  source_code_hash = data.archive_file.platform_log_rec.output_base64sha256

  tags = {
    Purpose  = "log-rec"
    TierItem = "T0.7a"
  }
}

resource "aws_lambda_function" "log_decision" {
  provider         = aws.platform
  function_name    = "agent-platform-log-decision"
  runtime          = "python3.12"
  handler          = "handler.handler"
  role             = aws_iam_role.platform_lambda_execution.arn
  filename         = data.archive_file.platform_log_decision.output_path
  source_code_hash = data.archive_file.platform_log_decision.output_base64sha256

  tags = {
    Purpose  = "log-decision"
    TierItem = "T0.7b"
  }
}

resource "aws_lambda_function" "query" {
  provider         = aws.platform
  function_name    = "agent-platform-query"
  runtime          = "python3.12"
  handler          = "handler.handler"
  role             = aws_iam_role.platform_lambda_execution.arn
  filename         = data.archive_file.platform_query.output_path
  source_code_hash = data.archive_file.platform_query.output_base64sha256

  tags = {
    Purpose  = "query"
    TierItem = "T0.7c"
  }
}

resource "aws_lambda_function" "update_rec" {
  provider         = aws.platform
  function_name    = "agent-platform-update-rec"
  runtime          = "python3.12"
  handler          = "handler.handler"
  role             = aws_iam_role.platform_lambda_execution.arn
  filename         = data.archive_file.platform_update_rec.output_path
  source_code_hash = data.archive_file.platform_update_rec.output_base64sha256

  tags = {
    Purpose  = "update-rec"
    TierItem = "T1.1"
  }
}

resource "aws_lambda_function" "list_tools" {
  provider         = aws.platform
  function_name    = "agent-platform-list-tools"
  runtime          = "python3.12"
  handler          = "handler.handler"
  role             = aws_iam_role.platform_lambda_execution.arn
  filename         = data.archive_file.platform_list_tools.output_path
  source_code_hash = data.archive_file.platform_list_tools.output_base64sha256

  tags = {
    Purpose  = "list-tools"
    TierItem = "T1.3"
  }
}

resource "aws_lambda_function" "maintenance" {
  provider         = aws.platform
  function_name    = "agent-platform-maintenance"
  runtime          = "python3.12"
  handler          = "handler.handler"
  role             = aws_iam_role.platform_lambda_execution.arn
  filename         = data.archive_file.platform_maintenance.output_path
  source_code_hash = data.archive_file.platform_maintenance.output_base64sha256

  tags = {
    Purpose  = "maintenance"
    TierItem = "T1.4"
  }
}

# ---------------------------------------------------------------------------
# Function URLs (AWS_IAM auth -- callers must sign requests with SigV4)
# ---------------------------------------------------------------------------

resource "aws_lambda_function_url" "log_rec" {
  provider           = aws.platform
  function_name      = aws_lambda_function.log_rec.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function_url" "log_decision" {
  provider           = aws.platform
  function_name      = aws_lambda_function.log_decision.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function_url" "query" {
  provider           = aws.platform
  function_name      = aws_lambda_function.query.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function_url" "update_rec" {
  provider           = aws.platform
  function_name      = aws_lambda_function.update_rec.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function_url" "list_tools" {
  provider           = aws.platform
  function_name      = aws_lambda_function.list_tools.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_function_url" "maintenance" {
  provider           = aws.platform
  function_name      = aws_lambda_function.maintenance.function_name
  authorization_type = "AWS_IAM"
}

# ---------------------------------------------------------------------------
# CloudWatch log groups (30-day retention)
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "log_rec" {
  provider          = aws.platform
  name              = "/aws/lambda/${aws_lambda_function.log_rec.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "log_decision" {
  provider          = aws.platform
  name              = "/aws/lambda/${aws_lambda_function.log_decision.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "query" {
  provider          = aws.platform
  name              = "/aws/lambda/${aws_lambda_function.query.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "update_rec" {
  provider          = aws.platform
  name              = "/aws/lambda/${aws_lambda_function.update_rec.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "list_tools" {
  provider          = aws.platform
  name              = "/aws/lambda/${aws_lambda_function.list_tools.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "maintenance" {
  provider          = aws.platform
  name              = "/aws/lambda/${aws_lambda_function.maintenance.function_name}"
  retention_in_days = 30
}
