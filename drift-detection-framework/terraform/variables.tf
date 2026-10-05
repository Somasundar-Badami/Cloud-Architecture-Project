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
