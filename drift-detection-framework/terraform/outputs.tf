# outputs.tf

output "bucket_name" {
  description = "Name of the deployed demo S3 bucket -- pass this to src/aws_state.py."
  value       = aws_s3_bucket.demo.bucket
}

output "bucket_arn" {
  description = "ARN of the deployed demo S3 bucket."
  value       = aws_s3_bucket.demo.arn
}

output "aws_region" {
  description = "Region the demo resources were deployed into."
  value       = var.aws_region
}

output "security_group_id" {
  description = "Monitored security group."
  value       = aws_security_group.demo.id
}

output "iam_role_name" {
  description = "Monitored IAM role."
  value       = aws_iam_role.demo.name
}

output "artifacts_bucket" {
  description = "Private bucket holding the desired-state document."
  value       = aws_s3_bucket.artifacts.id
}

output "drift_records_table" {
  description = "DynamoDB table with every scan result."
  value       = aws_dynamodb_table.drift_records.name
}

output "alerts_topic_arn" {
  description = "SNS topic for High/Critical drift alerts."
  value       = aws_sns_topic.alerts.arn
}

output "detector_function_name" {
  description = "Run a scan now: aws lambda invoke --function-name <this> out.json"
  value       = aws_lambda_function.detector.function_name
}

output "api_url" {
  description = "Dashboard API base URL (Cognito token required)."
  value       = aws_apigatewayv2_api.dashboard.api_endpoint
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.dashboard.id
}

output "cognito_client_id" {
  value = aws_cognito_user_pool_client.dashboard.id
}

output "cloudwatch_dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.pipeline.dashboard_name}"
}
