# Cost Monitoring and Budget Alerts
# Prevent unexpected AWS bills

#
# AWS Cost Explorer Budget
#

resource "aws_budgets_budget" "monthly_cost" {
  name              = "${var.environment}-monthly-cost-budget"
  budget_type       = "COST"
  limit_amount      = var.monthly_budget_usd
  limit_unit        = "USD"
  time_period_start = "2024-01-01_00:00"
  time_unit         = "MONTHLY"

  cost_filter {
    name = "TagKeyValue"
    values = [
      "Project$Machine Learning Trading System"
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.owner_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.owner_email]
  }
}

# Per-Service Budgets for Granular Tracking
resource "aws_budgets_budget" "sagemaker_cost" {
  name              = "${var.environment}-sagemaker-budget"
  budget_type       = "COST"
  limit_amount      = var.sagemaker_monthly_budget_usd
  limit_unit        = "USD"
  time_period_start = "2024-01-01_00:00"
  time_unit         = "MONTHLY"

  cost_filter {
    name = "Service"
    values = [
      "Amazon SageMaker"
    ]
  }

  cost_filter {
    name = "TagKeyValue"
    values = [
      "Project$Machine Learning Trading System"
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 90
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.owner_email]
  }
}

resource "aws_budgets_budget" "athena_cost" {
  name              = "${var.environment}-athena-budget"
  budget_type       = "COST"
  limit_amount      = var.athena_monthly_budget_usd
  limit_unit        = "USD"
  time_period_start = "2024-01-01_00:00"
  time_unit         = "MONTHLY"

  cost_filter {
    name = "Service"
    values = [
      "Amazon Athena"
    ]
  }

  cost_filter {
    name = "TagKeyValue"
    values = [
      "Project$Machine Learning Trading System"
    ]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 90
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.owner_email]
  }
}

#
# CloudWatch Dashboard for Cost Monitoring
#

resource "aws_cloudwatch_dashboard" "cost_monitoring" {
  dashboard_name = "${var.environment}-cost-monitoring"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "Estimated Monthly Cost (USD)"
          region = var.aws_region
          metrics = [
            ["AWS/Billing", "EstimatedCharges", "Currency", "USD"]
          ]
          period = 86400
          stat   = "Maximum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "SageMaker Training Hours"
          region = var.aws_region
          metrics = [
            ["AWS/Sagemaker", "TrainingTimeSeconds", { stat = "Sum" }]
          ]
          period = 86400
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Athena Data Scanned (GB)"
          region = var.aws_region
          metrics = [
            ["AWS/Athena", "DataScannedInBytes", { stat = "Sum" }]
          ]
          period = 86400
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "S3 Storage (GB)"
          region = var.aws_region
          metrics = [
            ["AWS/S3", "BucketSizeBytes", "BucketName", aws_s3_bucket.formulas_discovery.bucket, { stat = "Average" }],
            ["...", aws_s3_bucket.formulas_staging.bucket, { stat = "Average" }],
            ["...", aws_s3_bucket.formulas_production.bucket, { stat = "Average" }]
          ]
          period = 86400
          stat   = "Average"
          view   = "timeSeries"
        }
      }
    ]
  })
}

#
# Cost Anomaly Detection
#

resource "aws_ce_anomaly_monitor" "trading_system" {
  name              = "${var.environment}-trading-anomaly-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "trading_system" {
  name      = "${var.environment}-trading-anomaly-subscription"
  frequency = "DAILY"

  monitor_arn_list = [
    aws_ce_anomaly_monitor.trading_system.arn
  ]

  subscriber {
    type    = "EMAIL"
    address = var.owner_email
  }

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      values        = [tostring(var.anomaly_threshold_usd)]
      match_options = ["GREATER_THAN_OR_EQUAL"]
    }
  }
}

#
# Tag-Based Cost Allocation
# NOTE: Cost Categories require AWS Organizations Management Account access
# Disabled for linked accounts
#

# resource "aws_ce_cost_category" "trading_phases" {
#   name         = "${var.environment}-trading-phases"
#   rule_version = "CostCategoryExpression.v1"
#
#   rule {
#     value = "Phase_1_Infrastructure"
#     rule {
#       tags {
#         key           = "Phase"
#         values        = ["Phase_1_Infrastructure"]
#         match_options = ["EQUALS"]
#       }
#     }
#   }
#
#   rule {
#     value = "Phase_2_Formula_Integration"
#     rule {
#       tags {
#         key           = "Phase"
#         values        = ["Phase_2_Formula_Integration"]
#         match_options = ["EQUALS"]
#       }
#     }
#   }
#
#   rule {
#     value = "Phase_3_AB_Testing"
#     rule {
#       tags {
#         key           = "Phase"
#         values        = ["Phase_3_AB_Testing"]
#         match_options = ["EQUALS"]
#       }
#     }
#   }
#
#   rule {
#     value = "Phase_4_Circuit_Breakers"
#     rule {
#       tags {
#         key           = "Phase"
#         values        = ["Phase_4_Circuit_Breakers"]
#         match_options = ["EQUALS"]
#       }
#     }
#   }
#
#   rule {
#     value = "Phase_5_Monitoring"
#     rule {
#       tags {
#         key           = "Phase"
#         values        = ["Phase_5_Monitoring"]
#         match_options = ["EQUALS"]
#       }
#     }
#   }
#
#   rule {
#     value = "Phase_6_Auto_Weighting"
#     rule {
#       tags {
#         key           = "Phase"
#         values        = ["Phase_6_Auto_Weighting"]
#         match_options = ["EQUALS"]
#       }
#     }
#   }
# }
