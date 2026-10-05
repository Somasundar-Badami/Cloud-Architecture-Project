# variables.tf
#
# All inputs have safe, student-account-friendly defaults. No secrets are
# defined or accepted here -- do not add access-key variables to this file.

variable "aws_region" {
  description = "AWS region to deploy the demo bucket into."
  type        = string
  default     = "us-east-1"
}

variable "project_prefix" {
  description = "Short, clear prefix used to name the demo bucket so it is easy to identify and clean up."
  type        = string
  default     = "drift-demo"
}

variable "environment" {
  description = "Environment tag applied to the demo bucket (e.g. dev, sandbox)."
  type        = string
  default     = "sandbox"
}

variable "alert_email" {
  description = "Email address subscribed to High/Critical drift alerts (SNS). AWS sends a confirmation email that must be accepted. Empty = no subscription."
  type        = string
  default     = ""
}

variable "dashboard_user_email" {
  description = "Email of the first dashboard user. Cognito emails a temporary password to it. Empty = create users later in the console."
  type        = string
  default     = ""
}

variable "scan_schedule" {
  description = "EventBridge schedule expression for the drift scan."
  type        = string
  default     = "rate(1 hour)"
}

variable "enable_aws_config" {
  description = "Also create an AWS Config recorder for the 3 monitored resource types and trigger a scan on every configuration change. Leave false if the account/region already has a Config recorder (only one is allowed)."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda functions."
  type        = number
  default     = 14
}
