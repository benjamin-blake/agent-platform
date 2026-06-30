# Core Infrastructure Variables

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "eu-west-2"
}

variable "aws_profile" {
  description = "AWS SSO profile name"
  type        = string
  default     = "company-aws-profile"
}

variable "environment" {
  description = "Environment name (company|personal)"
  type        = string
  default     = "company"

  validation {
    condition     = contains(["company", "personal"], var.environment)
    error_message = "Environment must be either 'company' or 'personal'."
  }
}

variable "owner_email" {
  description = "Email address for cost alerts and notifications"
  type        = string
}

# S3 Configuration

variable "s3_bucket_prefix" {
  description = "Prefix for S3 bucket names (will create: prefix-formulas-discovery, etc.)"
  type        = string
}

# Glue Configuration

variable "glue_database_name" {
  description = "Glue catalog database name for Iceberg tables"
  type        = string
  default     = "formulas_db"
}

variable "project_name" {
  description = "Project name for resource identification"
  type        = string
  default     = "agent-platform"
}

# Cost Monitoring Variables

variable "monthly_budget_usd" {
  description = "Total monthly budget for all AWS services (USD)"
  type        = number
  default     = 190.0
}

variable "sagemaker_monthly_budget_usd" {
  description = "Monthly budget for SageMaker formula discovery (USD)"
  type        = number
  default     = 150.0
}

variable "athena_monthly_budget_usd" {
  description = "Monthly budget for Athena queries (USD)"
  type        = number
  default     = 30.0
}

variable "anomaly_threshold_usd" {
  description = "Cost anomaly detection threshold (USD)"
  type        = number
  default     = 50.0
}

# Monitoring & Alerting Variables

variable "sns_alert_topic_arn" {
  description = "SNS topic ARN for CloudWatch alarms (optional)"
  type        = string
  default     = ""
}

variable "slack_webhook_url" {
  description = "Slack webhook URL for notifications (optional)"
  type        = string
  default     = ""
  sensitive   = true
}

# SageMaker Configuration

variable "sagemaker_instance_type" {
  description = "SageMaker instance type for formula discovery"
  type        = string
  default     = "ml.t3.xlarge"
}

variable "sagemaker_max_runtime_seconds" {
  description = "Maximum runtime for SageMaker jobs (prevents runaway costs)"
  type        = number
  default     = 10800 # 3 hours
}

# Athena Configuration

variable "athena_lab_workgroup" {
  description = "Athena workgroup name for lab queries"
  type        = string
  default     = "formula-discovery-lab"
}

variable "athena_data_scanned_gb_limit" {
  description = "Maximum GB of data Athena can scan per query"
  type        = number
  default     = 100
}

# Data Pipeline Configuration

variable "data_pipeline_schedule_enabled" {
  description = "Whether the daily EventBridge schedule is enabled (set false to pause)"
  type        = bool
  default     = false
}

# Platform Account Variables

variable "platform_account_id" {
  # No committed default (PLAN-public-migration Step 9): the personal account ID must not be a
  # committed literal. Supplied via gitignored tfvars if the work root is ever applied (it is not,
  # post-CD.21). Still referenced by lambda_tooling_iam.tf, so the variable is retained.
  description = "Personal AWS account id hosting the platform Lambda surface (agent_platform profile target)"
  type        = string
}

variable "platform_profile_name" {
  description = "AWS SSO profile name for the personal platform account"
  type        = string
  default     = "agent_platform"
}

variable "platform_region" {
  description = "AWS region for platform Lambda resources"
  type        = string
  default     = "eu-west-2"
}
