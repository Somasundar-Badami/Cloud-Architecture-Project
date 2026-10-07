# monitoring.tf
#
# CloudWatch alarms + dashboard and an AWS Budget so the project can never
# silently cost money. Free tier: 10 alarms, 3 dashboards, 2 budgets.

resource "aws_cloudwatch_metric_alarm" "detector_errors" {
  alarm_name          = "${local.name_prefix}-detector-errors"
  alarm_description   = "The drift detector Lambda failed."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.detector.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "critical_drift" {
  alarm_name          = "${local.name_prefix}-critical-drift"
  alarm_description   = "At least one Critical-risk drift was detected."
  namespace           = "InfraDriftGuard"
  metric_name         = "DriftDetected"
  dimensions          = { RiskLevel = "Critical" }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name_prefix}-drift"
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "Drift detections by risk level"
          region  = var.aws_region
          stat    = "Sum"
          period  = 3600
          view    = "timeSeries"
          stacked = true
          metrics = [for level in ["Critical", "High", "Medium", "Low", "Review"] :
            ["InfraDriftGuard", "DriftDetected", "RiskLevel", level]
          ]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Detector Lambda health"
          region = var.aws_region
          period = 3600
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.detector.function_name, { stat = "Sum" }],
            [".", "Errors", ".", ".", { stat = "Sum" }],
            [".", "Duration", ".", ".", { stat = "Average", yAxis = "right" }],
          ]
        }
      },
      {
        type = "log", x = 0, y = 6, width = 24, height = 6
        properties = {
          title  = "Latest scan results"
          region = var.aws_region
          query  = "SOURCE '${aws_cloudwatch_log_group.detector.name}' | fields @timestamp, resource_id, has_drift, risk, remediation | filter level = 'INFO' | sort @timestamp desc | limit 20"
          view   = "table"
        }
      },
    ]
  })
}

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
