terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # AWS SSO Authentication
  profile = var.aws_profile # company-aws-profile

  default_tags {
    tags = {
      Project     = "ML_Trading_System"
      Environment = var.environment
      ManagedBy   = "Terraform"
      Owner       = var.owner_email
      CostCenter  = "RD"
    }
  }
}

provider "aws" {
  alias   = "platform"
  region  = var.platform_region
  profile = var.platform_profile_name

  default_tags {
    tags = {
      Project     = "agent-platform"
      Environment = "platform"
      Owner       = "bblake"
      ManagedBy   = "Terraform"
    }
  }
}

#
# S3 Buckets for Formula Lifecycle
# Discovery → Staging → Production
#

# Discovery: Raw formulas from SageMaker PySR
resource "aws_s3_bucket" "formulas_discovery" {
  bucket = "${var.s3_bucket_prefix}-formulas-discovery"

  tags = {
    Name    = "Formula Discovery Bucket"
    Purpose = "Raw formulas from SageMaker PySR"
    Phase   = "Phase_1_Infrastructure"
  }
}

# Staging: Formulas undergoing A/B testing
resource "aws_s3_bucket" "formulas_staging" {
  bucket = "${var.s3_bucket_prefix}-formulas-staging"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "Formula Staging Bucket"
    Purpose = "Formulas in AB testing"
    Phase   = "Phase_3_AB_Testing"
  }
}

# Production: Validated formulas for live trading
resource "aws_s3_bucket" "formulas_production" {
  bucket = "${var.s3_bucket_prefix}-formulas-production"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "Formula Production Bucket"
    Purpose = "Validated formulas for trading"
    Phase   = "Phase_3_AB_Testing"
  }
}

# Data Lake: Iceberg tables for market data and backtest results
resource "aws_s3_bucket" "data_lake" {
  bucket = "${var.s3_bucket_prefix}-data-lake"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "Data Lake Bucket"
    Purpose = "Iceberg tables for market data and backtest results"
    Phase   = "Phase_1_Infrastructure"
  }
}

# S3 Bucket Versioning (for all formula buckets)
resource "aws_s3_bucket_versioning" "formulas_discovery" {
  bucket = aws_s3_bucket.formulas_discovery.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "formulas_staging" {
  bucket = aws_s3_bucket.formulas_staging.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_versioning" "formulas_production" {
  bucket = aws_s3_bucket.formulas_production.id

  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Encryption (for all formula buckets)
resource "aws_s3_bucket_server_side_encryption_configuration" "formulas_discovery" {
  bucket = aws_s3_bucket.formulas_discovery.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "formulas_staging" {
  bucket = aws_s3_bucket.formulas_staging.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "formulas_production" {
  bucket = aws_s3_bucket.formulas_production.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Encryption for data lake
resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 Versioning for data lake
resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Lifecycle Policies
resource "aws_s3_bucket_lifecycle_configuration" "formulas_discovery" {
  bucket = aws_s3_bucket.formulas_discovery.id

  rule {
    id     = "archive-old-formulas"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365 # Delete after 1 year
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "formulas_staging" {
  bucket = aws_s3_bucket.formulas_staging.id

  rule {
    id     = "archive-old-formulas"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "formulas_production" {
  bucket = aws_s3_bucket.formulas_production.id

  rule {
    id     = "archive-old-formulas"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

# Glue Catalog Database
resource "aws_glue_catalog_database" "trading_db" {
  name        = var.glue_database_name
  description = "Trading data lake with Iceberg tables for formula lineage"
}

# Athena Workgroup for Lab
resource "aws_athena_workgroup" "lab" {
  name        = "${var.project_name}-lab"
  description = "Workgroup for research and formula discovery"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data_lake.id}/athena/lab-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }

  tags = {
    Name        = "Lab Workgroup"
    Environment = var.environment
  }
}

# Athena Workgroup for Production queries
resource "aws_athena_workgroup" "production" {
  name        = "${var.project_name}-production"
  description = "Workgroup for production queries"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data_lake.id}/athena/prod-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }

  tags = {
    Name        = "Production Workgroup"
    Environment = var.environment
  }
}

# IAM role for Athena/Glue access
resource "aws_iam_role" "athena_execution" {
  name = "${var.project_name}-athena-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "athena.amazonaws.com"
        }
      }
    ]
  })
}

# Agent Logs: Append-only log storage for cron agents (eliminates git write access requirement)
resource "aws_s3_bucket" "agent_logs" {
  bucket = "agent-platform-agent-logs"

  tags = {
    Name    = "Agent Logs Bucket"
    Purpose = "Append-only log storage for cron agents"
    Phase   = "Phase_1_Infrastructure"
  }
}

resource "aws_s3_bucket_versioning" "agent_logs" {
  bucket = aws_s3_bucket.agent_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "agent_logs" {
  bucket = aws_s3_bucket.agent_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "agent_logs" {
  bucket = aws_s3_bucket.agent_logs.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "aws_s3_bucket_public_access_block" "agent_logs" {
  bucket = aws_s3_bucket.agent_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "agent_logs_https_only" {
  bucket = aws_s3_bucket.agent_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyNonHTTPS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          "${aws_s3_bucket.agent_logs.arn}",
          "${aws_s3_bucket.agent_logs.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "athena_s3_access" {
  name = "athena-s3-access"
  role = aws_iam_role.athena_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          "s3:PutObject"
        ]
        Resource = [
          "${aws_s3_bucket.data_lake.arn}",
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetPartitions"
        ]
        Resource = "*"
      }
    ]
  })
}
