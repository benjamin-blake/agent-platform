# S3 Bucket Outputs

output "s3_formulas_discovery_bucket" {
  description = "Name of the S3 bucket for discovered formulas"
  value       = aws_s3_bucket.formulas_discovery.id
}

output "s3_formulas_staging_bucket" {
  description = "Name of the S3 bucket for formulas in A/B testing"
  value       = aws_s3_bucket.formulas_staging.id
}

output "s3_formulas_production_bucket" {
  description = "Name of the S3 bucket for production formulas"
  value       = aws_s3_bucket.formulas_production.id
}

# Glue Catalog Outputs

output "glue_database_name" {
  description = "Name of the Glue catalog database"
  value       = aws_glue_catalog_database.trading_db.name
}

output "glue_formula_lineage_table" {
  description = "Name of the Iceberg formula lineage table"
  value       = data.aws_glue_catalog_table.iceberg_tables["formula_lineage"].name
}

output "glue_trading_performance_table" {
  description = "Name of the Iceberg trading performance table"
  value       = data.aws_glue_catalog_table.iceberg_tables["trading_performance"].name
}

output "glue_ab_test_results_table" {
  description = "Name of the Iceberg A/B test results table"
  value       = data.aws_glue_catalog_table.iceberg_tables["ab_test_results"].name
}

# Athena Workgroup Outputs

output "athena_lab_workgroup" {
  description = "Name of the Athena lab workgroup for formula discovery"
  value       = aws_athena_workgroup.lab.name
}

# CloudWatch Dashboard Outputs

output "cloudwatch_formula_performance_dashboard" {
  description = "URL to CloudWatch formula performance dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.formula_performance.dashboard_name}"
}

output "cloudwatch_cost_monitoring_dashboard" {
  description = "URL to CloudWatch cost monitoring dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.cost_monitoring.dashboard_name}"
}

# SNS Alert Topic Output

output "sns_alert_topic_arn" {
  description = "ARN of SNS topic for alerts (if created)"
  value       = try(aws_sns_topic.alerts[0].arn, "not-created")
}

# Cost Monitoring Outputs

output "monthly_budget" {
  description = "Monthly budget (USD)"
  value       = var.monthly_budget_usd
}

output "cost_anomaly_monitor_arn" {
  description = "ARN of cost anomaly monitor"
  value       = aws_ce_anomaly_monitor.trading_system.arn
}

# Data Pipeline Outputs

output "step_functions_state_machine_arn" {
  description = "ARN of the data pipeline Step Functions state machine"
  value       = aws_sfn_state_machine.data_pipeline.arn
}

output "step_functions_console_url" {
  description = "URL to the Step Functions console for the data pipeline"
  value       = "https://${var.aws_region}.console.aws.amazon.com/states/home?region=${var.aws_region}#/statemachines/view/${aws_sfn_state_machine.data_pipeline.arn}"
}

output "eventbridge_rule_name" {
  description = "Name of the EventBridge daily schedule rule"
  value       = aws_cloudwatch_event_rule.daily_data_pipeline.name
}

output "lambda_deployment_bucket" {
  description = "S3 bucket where Lambda zip packages are stored"
  value       = aws_s3_bucket.data_lake.id
}

output "aws_sdk_pandas_layer_arn" {
  description = "ARN of the AWS SDK Pandas managed layer"
  value       = local.aws_sdk_pandas_layer_arn
}

output "extras_layer_arn" {
  description = "ARN of the extras dependencies layer (yfinance, pyyaml)"
  value       = aws_lambda_layer_version.data_pipeline_extras.arn
}

# Agent Logs Bucket Outputs

output "agent_logs_bucket_name" {
  description = "Name of the S3 bucket for agent log storage"
  value       = aws_s3_bucket.agent_logs.id
}

output "agent_logs_bucket_arn" {
  description = "ARN of the S3 bucket for agent log storage"
  value       = aws_s3_bucket.agent_logs.arn
}

# Scheduled Agents Lambda Outputs

output "scheduled_agent_dispatcher_arn" {
  description = "ARN of the scheduled agent dispatcher Lambda"
  value       = aws_lambda_function.scheduled_agent_dispatcher.arn
}

output "findings_processor_arn" {
  description = "ARN of the findings processor Lambda"
  value       = aws_lambda_function.findings_processor.arn
}

output "github_pat_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the GitHub PAT"
  value       = aws_secretsmanager_secret.github_pat.arn
}
