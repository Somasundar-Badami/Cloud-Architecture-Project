# monitored_resources.tf
#
# Phase 2: the EC2 Security Group and IAM role the framework monitors (the
# S3 bucket is in main.tf). Both are free and harmless on their own:
#   - the security group lives in its own empty VPC and is attached to
#     nothing, so opening a port on it during a drift demo exposes nothing
#   - the IAM role can only be assumed from this account, needs MFA for its
#     single permission, and is capped by a permissions boundary
#
# Every value that defines "desired state" comes from the locals below and
# is reused by desired_state.tf, so the two cannot disagree.

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project_prefix}-${var.environment}"

  sg_internal_cidr      = "10.0.0.0/8"
  sg_public_cidr        = "0.0.0.0/0"
  sg_internal_service   = 5432
  sg_name               = "${local.name_prefix}-web"
  iam_role_name         = "${local.name_prefix}-app-role"
  iam_inline_policy     = "${local.name_prefix}-app-access"
  iam_trust_principal   = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
  iam_primary_actions   = ["s3:GetObject"]
  iam_primary_resources = ["${aws_s3_bucket.demo.arn}/*"]
}

# --- EC2 Security Group ------------------------------------------------------

resource "aws_vpc" "demo" {
  cidr_block = "10.20.0.0/16"
  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

# Rules are inline on purpose: any rule added outside Terraform shows up as
# drift in `terraform plan`, and `terraform apply` removes it again.
resource "aws_security_group" "demo" {
  name        = local.sg_name
  description = "Drift detection demo security group (attached to nothing)"
  vpc_id      = aws_vpc.demo.id

  ingress {
    description = "SSH from internal network"
    protocol    = "tcp"
    from_port   = 22
    to_port     = 22
    cidr_blocks = [local.sg_internal_cidr]
  }

  ingress {
    description = "RDP from internal network"
    protocol    = "tcp"
    from_port   = 3389
    to_port     = 3389
    cidr_blocks = [local.sg_internal_cidr]
  }

  ingress {
    description = "HTTPS from anywhere (intended public web port)"
    protocol    = "tcp"
    from_port   = 443
    to_port     = 443
    cidr_blocks = [local.sg_public_cidr]
  }

  ingress {
    description = "PostgreSQL from internal network"
    protocol    = "tcp"
    from_port   = local.sg_internal_service
    to_port     = local.sg_internal_service
    cidr_blocks = [local.sg_internal_cidr]
  }

  egress {
    description = "All outbound traffic to internal network only"
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = [local.sg_internal_cidr]
  }

  tags = {
    Name = local.sg_name
  }
}

# --- IAM role ----------------------------------------------------------------

resource "aws_iam_policy" "boundary" {
  name        = "${local.name_prefix}-boundary"
  description = "Permissions boundary for the drift demo role: read-only S3 at most."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:ListBucket"]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role" "demo" {
  name                 = local.iam_role_name
  description          = "Drift detection demo role (monitored resource)"
  permissions_boundary = aws_iam_policy.boundary.arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = local.iam_trust_principal }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "demo" {
  name = local.iam_inline_policy
  role = aws_iam_role.demo.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PrimaryAccess"
      Effect    = "Allow"
      Action    = local.iam_primary_actions
      Resource  = local.iam_primary_resources
      Condition = { Bool = { "aws:MultiFactorAuthPresent" = "true" } }
    }]
  })
}
