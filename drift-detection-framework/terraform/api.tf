# api.tf
#
# Dashboard backend: API Gateway (HTTP API) -> Lambda "api" -> DynamoDB.
# Every route requires a Cognito access token (JWT authorizer); users can
# only be created by an administrator (no self sign-up).

# --- Cognito -------------------------------------------------------------------

resource "aws_cognito_user_pool" "dashboard" {
  name                     = "${local.name_prefix}-dashboard-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "dashboard" {
  name                          = "${local.name_prefix}-dashboard"
  user_pool_id                  = aws_cognito_user_pool.dashboard.id
  generate_secret               = false # browser client
  explicit_auth_flows           = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors = "ENABLED"
  access_token_validity         = 1
  id_token_validity             = 1
  refresh_token_validity        = 1
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

resource "aws_cognito_user" "first_user" {
  count        = var.dashboard_user_email == "" ? 0 : 1
  user_pool_id = aws_cognito_user_pool.dashboard.id
  username     = var.dashboard_user_email
  # Cognito emails a temporary password; it must be changed at first login.
  desired_delivery_mediums = ["EMAIL"]
  attributes = {
    email          = var.dashboard_user_email
    email_verified = "true"
  }
}

# --- API Lambda ----------------------------------------------------------------

resource "aws_iam_role" "api" {
  name               = "${local.name_prefix}-api-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }

  statement {
    sid       = "ReadDriftRecords"
    actions   = ["dynamodb:Scan"]
    resources = [aws_dynamodb_table.drift_records.arn]
  }

  statement {
    sid       = "RunScan"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.detector.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.name_prefix}-api"
  description      = "Dashboard API: drift records, on-demand scan, custom analysis."
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "lambda_api.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 512
  timeout          = 29 # API Gateway HTTP API integration limit is 30 s

  environment {
    variables = {
      TABLE_NAME             = aws_dynamodb_table.drift_records.name
      DETECTOR_FUNCTION_NAME = aws_lambda_function.detector.function_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

# --- API Gateway -----------------------------------------------------------------

resource "aws_apigatewayv2_api" "dashboard" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"] # token-based auth, no cookies; tighten to the dashboard origin if hosted
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.dashboard.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.dashboard.id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.dashboard.id}"
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.dashboard.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 30000
}

resource "aws_apigatewayv2_route" "api" {
  for_each           = toset(["GET /drifts", "GET /resources", "POST /scan", "POST /analyze"])
  api_id             = aws_apigatewayv2_api.dashboard.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.dashboard.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/*"
}

# --- Dashboard configuration (read by dashboard/index.html) --------------------

resource "local_file" "dashboard_config" {
  filename = "${path.module}/../dashboard/config.js"
  content = <<-EOT
    // Generated by terraform/api.tf -- do not edit, do not commit.
    window.DRIFT_CONFIG = ${jsonencode({
  region   = var.aws_region
  apiUrl   = aws_apigatewayv2_api.dashboard.api_endpoint
  clientId = aws_cognito_user_pool_client.dashboard.id
})};
  EOT
}
