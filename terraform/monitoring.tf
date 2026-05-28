# CloudWatch Monitoring Infrastructure
# Phase 5: Dashboards, alarms, and observability

#
# CloudWatch Log Groups
#

resource "aws_cloudwatch_log_group" "sagemaker_jobs" {
  name              = "/aws/sagemaker/${var.environment}-formula-discovery"
  retention_in_days = 30

  tags = {
    Name  = "SageMaker Formula Discovery Logs"
    Phase = "Phase_2_Formula_Integration"
  }
}

resource "aws_cloudwatch_log_group" "trading_system" {
  name              = "/trading/${var.environment}/live"
  retention_in_days = 90

  tags = {
    Name  = "Trading System Logs"
    Phase = "Phase_5_Monitoring"
  }
}

resource "aws_cloudwatch_log_group" "ab_testing" {
  name              = "/trading/${var.environment}/ab-testing"
  retention_in_days = 90

  tags = {
    Name  = "AB Testing Logs"
    Phase = "Phase_3_AB_Testing"
  }
}

resource "aws_cloudwatch_log_group" "circuit_breakers" {
  name              = "/trading/${var.environment}/circuit-breakers"
  retention_in_days = 365 # Keep circuit breaker events long-term

  tags = {
    Name  = "Circuit Breaker Logs"
    Phase = "Phase_4_Circuit_Breakers"
  }
}

#
# CloudWatch Metrics - Custom Namespace
#

# Formula Performance Metrics
resource "aws_cloudwatch_dashboard" "formula_performance" {
  dashboard_name = "${var.environment}-formula-performance"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "Active Formulas by State"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "FormulaCount", "State", "production"],
            [".", ".", ".", "staging"],
            [".", ".", ".", "testing"],
            [".", ".", ".", "circuit_broken"]
          ]
          period = 300
          stat   = "Average"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Formula Win Rate"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "WinRate", { stat = "Average" }]
          ]
          period = 3600
          stat   = "Average"
          view   = "timeSeries"
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Formula Sharpe Ratio"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "SharpeRatio", { stat = "Average" }]
          ]
          period = 3600
          stat   = "Average"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Circuit Breaker Triggers"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "CircuitBreakerTriggered", { stat = "Sum" }]
          ]
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "A/B Test Evaluations"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "ABTestEvaluations", "Decision", "promote", { stat = "Sum" }],
            [".", ".", ".", "reject", { stat = "Sum" }],
            [".", ".", ".", "extend", { stat = "Sum" }]
          ]
          period = 86400
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "RAT Ensemble Latency (ms)"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "EnsembleLatency", { stat = "Average" }],
            ["...", { stat = "p95" }],
            ["...", { stat = "p99" }]
          ]
          period = 300
          stat   = "Average"
          view   = "timeSeries"
        }
      }
    ]
  })
}

# SageMaker Job Monitoring
resource "aws_cloudwatch_dashboard" "sagemaker_jobs" {
  dashboard_name = "${var.environment}-sagemaker-formula-discovery"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "SageMaker Job Status"
          region = var.aws_region
          metrics = [
            ["AWS/Sagemaker", "TrainingJobStatus", { stat = "Sum" }]
          ]
          period = 3600
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Formulas Discovered per Job"
          region = var.aws_region
          metrics = [
            ["TradingSystem", "FormulasDiscovered", { stat = "Sum" }]
          ]
          period = 3600
          stat   = "Sum"
          view   = "timeSeries"
        }
      },
      {
        type = "log"
        properties = {
          title  = "Recent SageMaker Errors"
          region = var.aws_region
          query  = <<-EOT
            SOURCE '${aws_cloudwatch_log_group.sagemaker_jobs.name}'
            | fields @timestamp, @message
            | filter @message like /ERROR/
            | sort @timestamp desc
            | limit 20
          EOT
        }
      }
    ]
  })
}

#
# CloudWatch Alarms
#

# Formula Count Alarm (detect if no formulas active)
resource "aws_cloudwatch_metric_alarm" "no_active_formulas" {
  alarm_name          = "${var.environment}-no-active-formulas"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FormulaCount"
  namespace           = "TradingSystem"
  period              = 300
  statistic           = "Average"
  threshold           = 1
  alarm_description   = "No active formulas in production"
  treat_missing_data  = "breaching"

  dimensions = {
    State = "production"
  }

  alarm_actions = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []
}

# Win Rate Alarm (detect portfolio degradation)
resource "aws_cloudwatch_metric_alarm" "low_win_rate" {
  alarm_name          = "${var.environment}-low-win-rate"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3
  metric_name         = "WinRate"
  namespace           = "TradingSystem"
  period              = 3600
  statistic           = "Average"
  threshold           = 40.0
  alarm_description   = "Portfolio win rate dropped below 40%"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []
}

# Circuit Breaker Alarm (many formulas failing)
resource "aws_cloudwatch_metric_alarm" "excessive_circuit_breakers" {
  alarm_name          = "${var.environment}-excessive-circuit-breakers"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "CircuitBreakerTriggered"
  namespace           = "TradingSystem"
  period              = 3600
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "More than 5 circuit breakers triggered in 1 hour"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []
}

# Ensemble Latency Alarm (slow predictions)
resource "aws_cloudwatch_metric_alarm" "high_ensemble_latency" {
  alarm_name          = "${var.environment}-high-ensemble-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "EnsembleLatency"
  namespace           = "TradingSystem"
  period              = 300
  statistic           = "Average"
  threshold           = 100.0 # 100ms
  alarm_description   = "Ensemble prediction latency > 100ms"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []
}

# SageMaker Job Failure Alarm
resource "aws_cloudwatch_metric_alarm" "sagemaker_job_failed" {
  alarm_name          = "${var.environment}-sagemaker-job-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "TrainingJobsFailed"
  namespace           = "AWS/Sagemaker"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "SageMaker formula discovery job failed"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.sns_alert_topic_arn != "" ? [var.sns_alert_topic_arn] : []
}

#
# SNS Topic for Alerts (optional, created if Slack webhook provided)
#

resource "aws_sns_topic" "alerts" {
  count = var.slack_webhook_url != "" ? 1 : 0

  name = "${var.environment}-trading-alerts"

  tags = {
    Name  = "Trading System Alerts"
    Phase = "Phase_5_Monitoring"
  }
}

# Lambda function to forward SNS to Slack
resource "aws_lambda_function" "sns_to_slack" {
  count = var.slack_webhook_url != "" ? 1 : 0

  filename      = "${path.module}/lambda/sns_to_slack.zip"
  function_name = "${var.environment}-sns-to-slack"
  role          = aws_iam_role.lambda_sns_to_slack[0].arn
  handler       = "index.handler"
  runtime       = "python3.11"

  environment {
    variables = {
      SLACK_WEBHOOK_URL = var.slack_webhook_url
    }
  }

  tags = {
    Name  = "SNS to Slack Forwarder"
    Phase = "Phase_5_Monitoring"
  }
}

resource "aws_iam_role" "lambda_sns_to_slack" {
  count = var.slack_webhook_url != "" ? 1 : 0

  name = "${var.environment}-lambda-sns-to-slack"

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
}

resource "aws_iam_role_policy_attachment" "lambda_sns_to_slack_basic" {
  count = var.slack_webhook_url != "" ? 1 : 0

  role       = aws_iam_role.lambda_sns_to_slack[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_sns_topic_subscription" "lambda" {
  count = var.slack_webhook_url != "" ? 1 : 0

  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.sns_to_slack[0].arn
}

resource "aws_lambda_permission" "sns" {
  count = var.slack_webhook_url != "" ? 1 : 0

  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sns_to_slack[0].function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alerts[0].arn
}
