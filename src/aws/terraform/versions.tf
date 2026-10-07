# versions.tf
#
# Pins Terraform and provider versions for reproducibility. No credentials
# are configured here -- the AWS provider uses the default credential
# chain (environment variables, ~/.aws/credentials, or an instance/role
# profile). NEVER hardcode access keys in this file or any .tf file.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "InfraDriftGuard"
      ManagedBy = "terraform"
    }
  }
  # Credentials are NOT set here. boto3/Terraform both resolve credentials
  # from the environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
  # AWS_SESSION_TOKEN), a shared ~/.aws/credentials profile, or an
  # attached IAM role -- whichever the operator has configured locally.
}
