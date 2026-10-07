# outputs.tf

output "bucket_name" {
  description = "Name of the monitored demo S3 bucket."
  value       = aws_s3_bucket.demo.bucket
}

output "bucket_arn" {
  description = "ARN of the monitored demo S3 bucket."
  value       = aws_s3_bucket.demo.arn
}

output "aws_region" {
  description = "Region the stack was deployed into."
  value       = var.aws_region
}

output "security_group_id" {
  description = "Monitored demo security group."
  value       = aws_security_group.monitored.id
}

output "iam_role_name" {
  description = "Monitored demo IAM role."
  value       = aws_iam_role.monitored.name
}

output "detector_function_name" {
  description = "Drift detector Lambda (invoke manually with `aws lambda invoke`)."
  value       = aws_lambda_function.detector.function_name
}

output "findings_table" {
  description = "DynamoDB table holding drift findings."
  value       = aws_dynamodb_table.findings.name
}

output "api_url" {
  description = "Base URL of the authenticated REST API."
  value       = aws_apigatewayv2_api.api.api_endpoint
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.users.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.dashboard.id
}

output "dashboard_url" {
  description = "CloudWatch dashboard."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
