# detector.tf
#
# Drift detector Lambda + its storage (DynamoDB), alerting (SNS) and
# schedule (EventBridge). Free-tier sizing: 256 MB, ~1-2 s per run,
# hourly schedule -> well under 1M requests / 400,000 GB-s per month.

# The deployment zip is assembled straight from the repo -- no separate
# build step. Shared modules from src/backend and src/aws/collectors are
# copied in unchanged next to the handler.
data "archive_file" "lambda_bundle" {
  type        = "zip"
  output_path = "${path.module}/.build/lambda_bundle.zip"

  source {
    content  = file("${path.module}/../lambda/detector_handler.py")
    filename = "detector_handler.py"
  }
  source {
    content  = file("${path.module}/../lambda/api_handler.py")
    filename = "api_handler.py"
  }
  source {
    content  = file("${path.module}/../lambda/rf_predict.py")
    filename = "rf_predict.py"
  }
  source {
    content  = file("${path.module}/../lambda/model/rf_model.json")
    filename = "model/rf_model.json"
  }
  source {
    content  = file("${path.module}/../../backend/drift_engine.py")
    filename = "drift_engine.py"
  }
  source {
    content  = file("${path.module}/../../backend/feature_extraction.py")
    filename = "feature_extraction.py"
  }
  source {
    content  = file("${path.module}/../collectors/aws_state.py")
    filename = "aws_state.py"
  }
  source {
    content  = file("${path.module}/../collectors/aws_normalizer.py")
    filename = "aws_normalizer.py"
  }
  source {
    content  = file("${path.module}/../collectors/sg_iam_collectors.py")
    filename = "sg_iam_collectors.py"
  }
}

# ---------------------------------------------------------------------------
# DynamoDB -- provisioned 1 RCU / 1 WCU stays inside the always-free 25/25.
# ---------------------------------------------------------------------------
resource "aws_dynamodb_table" "findings" {
  name           = "${local.name_prefix}-drift-findings"
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "resource_id"
  range_key      = "detected_at"

  attribute {
    name = "resource_id"
    type = "S"
  }
  attribute {
    name = "detected_at"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = false
  }

  server_side_encryption {
    enabled = true
  }

  point_in_time_recovery {
    enabled = false # PITR is billed; not needed for a demo
  }
}

# ---------------------------------------------------------------------------
# SNS -- email alerts (1,000 email deliveries/month free).
# ---------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  # Not encrypted with the AWS-managed aws/sns key on purpose: CloudWatch
  # alarms cannot publish to topics that use it.
  name = "${local.name_prefix}-drift-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------------------
# IAM role for the detector -- read-only collection + narrowly scoped writes.
# ---------------------------------------------------------------------------
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
  name               = "${local.name_prefix}-detector-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "detector" {
  statement {
    sid = "CollectS3"
    actions = [
      "s3:ListBucket", "s3:GetBucketAcl", "s3:GetBucketPolicy", "s3:GetBucketVersioning",
      "s3:GetBucketLogging", "s3:GetLifecycleConfiguration", "s3:GetEncryptionConfiguration",
      "s3:GetBucketPublicAccessBlock",
    ]
    resources = [aws_s3_bucket.demo.arn]
  }
  statement {
    sid       = "CollectSecurityGroups"
    actions   = ["ec2:DescribeSecurityGroups"]
    resources = ["*"] # Describe* does not support resource-level permissions
  }
  statement {
    sid       = "CollectIam"
    actions   = ["iam:GetRole", "iam:ListRolePolicies", "iam:GetRolePolicy"]
    resources = [aws_iam_role.monitored.arn]
  }
  statement {
    sid       = "Findings"
    actions   = ["dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.findings.arn]
  }
  statement {
    sid       = "Alerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["InfraDriftGuard"]
    }
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.detector.arn}:*"]
  }

  dynamic "statement" {
    for_each = var.auto_remediate ? [1] : []
    content {
      sid       = "RemediateS3"
      actions   = ["s3:PutBucketPublicAccessBlock"]
      resources = [aws_s3_bucket.demo.arn]
    }
  }
  dynamic "statement" {
    for_each = var.auto_remediate ? [1] : []
    content {
      sid       = "RemediateSecurityGroup"
      actions   = ["ec2:RevokeSecurityGroupIngress"]
      resources = ["arn:aws:ec2:${var.aws_region}:${local.account_id}:security-group/${aws_security_group.monitored.id}"]
    }
  }
}

resource "aws_iam_role_policy" "detector" {
  name   = "detector"
  role   = aws_iam_role.detector.id
  policy = data.aws_iam_policy_document.detector.json
}

resource "aws_cloudwatch_log_group" "detector" {
  name              = "/aws/lambda/${local.name_prefix}-drift-detector"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "detector" {
  function_name    = "${local.name_prefix}-drift-detector"
  role             = aws_iam_role.detector.arn
  runtime          = "python3.12"
  handler          = "detector_handler.lambda_handler"
  filename         = data.archive_file.lambda_bundle.output_path
  source_code_hash = data.archive_file.lambda_bundle.output_base64sha256
  memory_size      = 256
  timeout          = 60
  architectures    = ["arm64"] # cheaper per GB-s and fully covered by the free tier

  environment {
    variables = {
      DESIRED_STATE_JSON = jsonencode(local.desired_state)
      FINDINGS_TABLE     = aws_dynamodb_table.findings.name
      ALERT_TOPIC_ARN    = aws_sns_topic.alerts.arn
      ALERT_MIN_RISK     = var.alert_min_risk
      AUTO_REMEDIATE     = tostring(var.auto_remediate)
      METRIC_NAMESPACE   = "InfraDriftGuard"
    }
  }

  depends_on = [aws_cloudwatch_log_group.detector, aws_iam_role_policy.detector]
}

# ---------------------------------------------------------------------------
# EventBridge schedule
# ---------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.name_prefix}-drift-scan"
  description         = "Periodic InfraDriftGuard drift scan"
  schedule_expression = var.scan_schedule
}

resource "aws_cloudwatch_event_target" "detector" {
  rule = aws_cloudwatch_event_rule.schedule.name
  arn  = aws_lambda_function.detector.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
