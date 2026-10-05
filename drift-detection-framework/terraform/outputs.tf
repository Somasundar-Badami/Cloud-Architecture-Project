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
  description = "Region the demo bucket was deployed into."
  value       = var.aws_region
}
