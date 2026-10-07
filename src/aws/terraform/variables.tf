# variables.tf
#
# All inputs have safe, student-account-friendly defaults. No secrets are
# defined or accepted here -- do not add access-key variables to this file.

variable "aws_region" {
  description = "AWS region to deploy the demo bucket into."
  type        = string
  default     = "ap-southeast-2" # free-plan account is restricted to this region
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
  description = "Email address that receives drift alerts and budget warnings (SNS sends a confirmation link first)."
  type        = string
}

variable "admin_email" {
  description = "Email for the dashboard's first Cognito user (receives a temporary password). Defaults to alert_email."
  type        = string
  default     = ""
}

variable "scan_schedule" {
  description = "EventBridge schedule for drift scans. rate(1 hour) = ~720 Lambda runs/month, far below the 1M free requests."
  type        = string
  default     = "rate(1 hour)"
}

variable "alert_min_risk" {
  description = "Lowest risk level that triggers an SNS email (Low | Medium | High | Critical)."
  type        = string
  default     = "High"

  validation {
    condition     = contains(["Low", "Medium", "High", "Critical"], var.alert_min_risk)
    error_message = "alert_min_risk must be Low, Medium, High or Critical."
  }
}

variable "auto_remediate" {
  description = "Automatically revert Critical drift that has a safe fix (S3 public-access block, SSH/RDP open to 0.0.0.0/0)."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  description = "AWS Budget alarm threshold in USD -- emails you before anything costs real money."
  type        = number
  default     = 1
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention (short retention keeps storage inside the free tier)."
  type        = number
  default     = 7
}
