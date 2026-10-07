# monitored.tf
#
# The resources InfraDriftGuard WATCHES (in addition to the S3 bucket in
# main.tf), plus the desired-state document handed to the detector Lambda.
#
# All three resource families are free: an S3 bucket with no objects, a
# security group that is never attached to an instance, and an IAM role
# that nothing assumes.

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

locals {
  name_prefix  = "${var.project_prefix}-${var.environment}"
  account_id   = data.aws_caller_identity.current.account_id
  internal_net = "10.0.0.0/8"
  service_port = 5432
}

# ---------------------------------------------------------------------------
# Security group -- admin ports restricted to the internal network, only
# HTTPS public. Mirrors scenario_definitions.sg_baseline().
# ---------------------------------------------------------------------------
resource "aws_security_group" "monitored" {
  name        = "${local.name_prefix}-web-sg"
  description = "InfraDriftGuard monitored demo security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH from internal network only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.internal_net]
  }

  ingress {
    description = "RDP from internal network only"
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = [local.internal_net]
  }

  ingress {
    description = "Public HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "PostgreSQL from internal network"
    from_port   = local.service_port
    to_port     = local.service_port
    protocol    = "tcp"
    cidr_blocks = [local.internal_net]
  }

  egress {
    description = "Outbound to internal network only"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [local.internal_net]
  }
}

# ---------------------------------------------------------------------------
# IAM role -- least privilege, MFA-protected trust, permissions boundary.
# Mirrors scenario_definitions.iam_baseline().
# ---------------------------------------------------------------------------
resource "aws_iam_policy" "boundary" {
  name        = "${local.name_prefix}-boundary"
  description = "Permissions boundary for the monitored demo role"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["${aws_s3_bucket.demo.arn}/*"]
    }]
  })
}

resource "aws_iam_role" "monitored" {
  name                 = "${local.name_prefix}-app-role"
  permissions_boundary = aws_iam_policy.boundary.arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
      Condition = { Bool = { "aws:MultiFactorAuthPresent" = "true" } }
    }]
  })
}

resource "aws_iam_role_policy" "monitored" {
  name = "app-read-only"
  role = aws_iam_role.monitored.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["${aws_s3_bucket.demo.arn}/*"]
    }]
  })
}

# ---------------------------------------------------------------------------
# Desired state, rendered from the resources above. The Lambda compares
# live AWS configuration against exactly this -- so Terraform remains the
# single source of truth. Field names/shapes match the normalizers in
# src/aws/collectors/ (verified by tests/test_lambda_detector.py).
# ---------------------------------------------------------------------------
locals {
  desired_state = [
    {
      resource_id   = aws_s3_bucket.demo.bucket
      resource_type = "s3_bucket"
      desired = {
        resource_type           = "aws_s3_bucket"
        bucket_name             = aws_s3_bucket.demo.bucket
        block_public_access     = true
        acl                     = "private"
        encryption              = { enabled = true, kms_key_id = null }
        versioning              = "disabled"
        logging                 = "disabled"
        lifecycle_rule          = null
        bucket_policy_principal = "arn:aws:iam::${local.account_id}:root"
      }
    },
    {
      resource_id   = aws_security_group.monitored.id
      resource_type = "security_group"
      desired = {
        resource_type         = "aws_security_group"
        sg_id                 = aws_security_group.monitored.id
        instance_name         = aws_security_group.monitored.name
        inbound_ssh           = { port = 22, source_cidr = local.internal_net }
        inbound_rdp           = { port = 3389, source_cidr = local.internal_net }
        inbound_https         = { port = 443, source_cidr = "0.0.0.0/0" }
        inbound_custom        = null
        outbound_default      = { port = "all", destination_cidr = local.internal_net }
        internal_service_port = { port = local.service_port, range = "single" }
        peer_sg_reference     = null
      }
    },
    {
      resource_id   = aws_iam_role.monitored.name
      resource_type = "iam_policy"
      desired = {
        resource_type        = "aws_iam_entity"
        entity_name          = aws_iam_role.monitored.name
        actions              = ["s3:GetObject"]
        resources            = ["${aws_s3_bucket.demo.arn}/*"]
        effect               = "Allow"
        requires_mfa         = true
        trust_principal      = "arn:aws:iam::${local.account_id}:root"
        permissions_boundary = aws_iam_policy.boundary.arn
        group_membership     = null
      }
    },
  ]
}
