# pipeline.tf
#
# Detection pipeline:
#   EventBridge schedule / AWS Config change event
#     -> Lambda "detector" (boto3 collect -> drift -> features -> RF + SHAP)
#     -> DynamoDB drift records
#     -> SNS alert for High/Critical
#   CloudWatch: Lambda logs, custom metrics (Embedded Metric Format),
#   alarms and a dashboard.
#
# The ML model runs inside Lambda from models/portable_model.json (a JSON
# export of the trained Random Forest; see src/portable_model.py), so no
# SageMaker endpoint is billed while idle.

locals {
  lambda_sources = [
    "drift_engine.py",
    "feature_extraction.py",
    "aws_state.py",
    "aws_normalizer.py",
    "portable_model.py",
    "drift_pipeline.py",
    "lambda_detector.py",
    "lambda_api.py",
  ]
}

data "archive_file" "lambda" {
  type        = "zip"
  output_path = "${path.module}/build/lambda.zip"

  dynamic "source" {
    for_each = toset(local.lambda_sources)
    content {
      content  = file("${path.module}/../src/${source.value}")
      filename = source.value
    }
  }

  source {
    content  = file("${path.module}/../models/portable_model.json")
    filename = "portable_model.json"
  }
}

# --- Storage + notifications ------------------------------------------------

resource "aws_dynamodb_table" "drift_records" {
  name         = "${local.name_prefix}-drift-records"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "resource_id"
  range_key    = "detected_at"

  attribute {
    name = "resource_id"
    type = "S"
  }

  attribute {
    name = "detected_at"
    type = "S"
  }

  point_in_time_recovery {
    enabled = false
  }
}

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-drift-alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Detector Lambda ---------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "detector" {
  name               = "${local.name_prefix}-detector-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "detector" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.detector.arn}:*"]
  }

  statement {
    sid       = "ReadDesiredState"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.artifacts.arn}/desired-state/*"]
  }

  statement {
    sid = "ReadMonitoredBucketConfig"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketAcl",
      "s3:GetEncryptionConfiguration",
      "s3:GetBucketVersioning",
      "s3:GetBucketLogging",
      "s3:GetLifecycleConfiguration",
      "s3:GetBucketPolicy",
    ]
    resources = [aws_s3_bucket.demo.arn]
  }

  statement {
    sid       = "ReadSecurityGroups"
    actions   = ["ec2:DescribeSecurityGroups"]
    resources = ["*"] # DescribeSecurityGroups does not support resource-level permissions
  }

  statement {
    sid       = "ReadMonitoredRole"
    actions   = ["iam:GetRole", "iam:GetRolePolicy", "iam:ListAttachedRolePolicies"]
    resources = [aws_iam_role.demo.arn]
  }

  statement {
    sid       = "DriftRecords"
    actions   = ["dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.drift_records.arn]
  }

  statement {
    sid       = "Alerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "detector" {
  name   = "detector"
  role   = aws_iam_role.detector.id
  policy = data.aws_iam_policy_document.detector.json
}

resource "aws_cloudwatch_log_group" "detector" {
  name              = "/aws/lambda/${local.name_prefix}-detector"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "detector" {
  function_name    = "${local.name_prefix}-detector"
  description      = "Scans monitored resources for drift, classifies risk, explains with SHAP, alerts."
  role             = aws_iam_role.detector.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "lambda_detector.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 512
  timeout          = 60

  environment {
    variables = {
      DESIRED_STATE_BUCKET = aws_s3_bucket.artifacts.id
      DESIRED_STATE_KEY    = aws_s3_object.desired_state.key
      TABLE_NAME           = aws_dynamodb_table.drift_records.name
      TOPIC_ARN            = aws_sns_topic.alerts.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.detector, aws_iam_role_policy.detector]
}

# --- Triggers ----------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "scan_schedule" {
  name                = "${local.name_prefix}-scan-schedule"
  description         = "Periodic drift scan"
  schedule_expression = var.scan_schedule
}

resource "aws_cloudwatch_event_target" "scan_schedule" {
  rule = aws_cloudwatch_event_rule.scan_schedule.name
  arn  = aws_lambda_function.detector.arn
}

resource "aws_lambda_permission" "scan_schedule" {
  statement_id  = "AllowScheduledScan"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scan_schedule.arn
}

# --- Optional: AWS Config as the change trigger ------------------------------

resource "aws_iam_role" "config" {
  count = var.enable_aws_config ? 1 : 0
  name  = "${local.name_prefix}-aws-config"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "config.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "config" {
  count      = var.enable_aws_config ? 1 : 0
  role       = aws_iam_role.config[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

resource "aws_s3_bucket_policy" "artifacts_config_delivery" {
  count  = var.enable_aws_config ? 1 : 0
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ConfigBucketCheck"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = ["s3:GetBucketAcl", "s3:ListBucket"]
        Resource  = aws_s3_bucket.artifacts.arn
        Condition = { StringEquals = { "AWS:SourceAccount" = data.aws_caller_identity.current.account_id } }
      },
      {
        Sid       = "ConfigDelivery"
        Effect    = "Allow"
        Principal = { Service = "config.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.artifacts.arn}/config/AWSLogs/${data.aws_caller_identity.current.account_id}/Config/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"      = "bucket-owner-full-control"
            "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

resource "aws_config_configuration_recorder" "this" {
  count    = var.enable_aws_config ? 1 : 0
  name     = "${local.name_prefix}-recorder"
  role_arn = aws_iam_role.config[0].arn

  recording_group {
    all_supported  = false
    resource_types = ["AWS::S3::Bucket", "AWS::EC2::SecurityGroup", "AWS::IAM::Role"]
  }
}

resource "aws_config_delivery_channel" "this" {
  count          = var.enable_aws_config ? 1 : 0
  name           = "${local.name_prefix}-delivery"
  s3_bucket_name = aws_s3_bucket.artifacts.id
  s3_key_prefix  = "config"
  depends_on     = [aws_config_configuration_recorder.this, aws_s3_bucket_policy.artifacts_config_delivery]
}

resource "aws_config_configuration_recorder_status" "this" {
  count      = var.enable_aws_config ? 1 : 0
  name       = aws_config_configuration_recorder.this[0].name
  is_enabled = true
  depends_on = [aws_config_delivery_channel.this]
}

resource "aws_cloudwatch_event_rule" "config_change" {
  count       = var.enable_aws_config ? 1 : 0
  name        = "${local.name_prefix}-config-change"
  description = "Scan when AWS Config records a change to a monitored resource"
  event_pattern = jsonencode({
    source        = ["aws.config"]
    "detail-type" = ["Config Configuration Item Change"]
    detail = {
      configurationItem = {
        resourceName = [aws_s3_bucket.demo.bucket, aws_iam_role.demo.name]
      }
    }
  })
}

resource "aws_cloudwatch_event_rule" "config_change_sg" {
  count       = var.enable_aws_config ? 1 : 0
  name        = "${local.name_prefix}-config-change-sg"
  description = "Scan when AWS Config records a change to the monitored security group"
  event_pattern = jsonencode({
    source        = ["aws.config"]
    "detail-type" = ["Config Configuration Item Change"]
    detail = {
      configurationItem = {
        resourceId = [aws_security_group.demo.id]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "config_change" {
  for_each = var.enable_aws_config ? {
    named = aws_cloudwatch_event_rule.config_change[0].name
    sg    = aws_cloudwatch_event_rule.config_change_sg[0].name
  } : {}
  rule = each.value
  arn  = aws_lambda_function.detector.arn
}

resource "aws_lambda_permission" "config_change" {
  for_each = var.enable_aws_config ? {
    named = aws_cloudwatch_event_rule.config_change[0].arn
    sg    = aws_cloudwatch_event_rule.config_change_sg[0].arn
  } : {}
  statement_id  = "AllowConfigChangeScan-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = each.value
}

# --- CloudWatch monitoring ---------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "detector_errors" {
  alarm_name          = "${local.name_prefix}-detector-errors"
  alarm_description   = "The drift detector Lambda failed."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.detector.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "collection_errors" {
  alarm_name          = "${local.name_prefix}-collection-errors"
  alarm_description   = "A monitored resource could not be read (deleted, or permissions changed)."
  namespace           = "DriftDetection"
  metric_name         = "CollectionErrors"
  dimensions          = { FunctionName = aws_lambda_function.detector.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_dashboard" "pipeline" {
  dashboard_name = "${local.name_prefix}-drift-pipeline"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Drift scans"
          region = var.aws_region
          stat   = "Sum"
          period = 3600
          metrics = [
            ["DriftDetection", "ResourcesScanned", "FunctionName", aws_lambda_function.detector.function_name],
            [".", "DriftsDetected", ".", "."],
            [".", "HighRiskDrifts", ".", "."],
            [".", "AlertsSent", ".", "."],
            [".", "CollectionErrors", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Detector Lambda health"
          region = var.aws_region
          period = 3600
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.detector.function_name, { stat = "Sum" }],
            [".", "Errors", ".", ".", { stat = "Sum" }],
            [".", "Duration", ".", ".", { stat = "Average" }],
          ]
        }
      },
    ]
  })
}
