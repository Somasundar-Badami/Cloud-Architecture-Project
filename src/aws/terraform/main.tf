# main.tf
#
# Provisions ONE dedicated demo S3 bucket for the Infrastructure Drift
# Detection Framework (Phase 1: S3 only). Deliberately minimal and safe
# for a student/sandbox AWS account:
#   - Public access fully blocked (all four sub-settings)
#   - Server-side encryption enabled (SSE-S3 / AES256, no extra KMS key
#     or KMS permissions required)
#   - Versioning explicitly set (not left ambiguous)
#   - No bucket policy attached (bucket-owner-only access)
#   - No lifecycle rule (kept out of scope for this minimal demo)
#   - No logging bucket (avoids provisioning a second bucket + policy
#     just for this demo)
#   - Clear, prefixed resource naming with a random suffix for S3's
#     global-uniqueness requirement
#
# This is the TERRAFORM-DECLARED DESIRED STATE. The Python normalizer
# (src/aws_normalizer.py) mirrors these exact settings into the project's
# normalized schema so drift_engine.detect_drift() can compare this
# desired state against whatever boto3 actually observes in AWS.

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

locals {
  bucket_name = "${var.project_prefix}-${var.environment}-${random_id.bucket_suffix.hex}"
}

resource "aws_s3_bucket" "demo" {
  bucket = local.bucket_name

  tags = {
    Project     = "infrastructure-drift-detection-framework"
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "drift-detection-demo-phase1-s3"
  }
}

# Block ALL public access -- all four sub-settings explicitly true.
resource "aws_s3_bucket_public_access_block" "demo" {
  bucket = aws_s3_bucket.demo.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Server-side encryption enabled by default (SSE-S3 / AES256 -- no KMS
# key or KMS IAM permissions required, keeping this safe/simple for a
# student account).
resource "aws_s3_bucket_server_side_encryption_configuration" "demo" {
  bucket = aws_s3_bucket.demo.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning explicitly declared (Disabled) rather than left to the
# provider default, so the desired state is unambiguous.
resource "aws_s3_bucket_versioning" "demo" {
  bucket = aws_s3_bucket.demo.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Explicit ACL: private (no public grants). Using the modern
# aws_s3_bucket_acl resource with the "private" canned ACL.
resource "aws_s3_bucket_ownership_controls" "demo" {
  bucket = aws_s3_bucket.demo.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

resource "aws_s3_bucket_acl" "demo" {
  depends_on = [aws_s3_bucket_ownership_controls.demo]
  bucket     = aws_s3_bucket.demo.id
  acl        = "private"
}

# Deliberately NOT declared (kept out of scope for this minimal, safe
# Phase-1 demo):
#   - aws_s3_bucket_policy        (no bucket policy -> bucket-owner-only)
#   - aws_s3_bucket_lifecycle_configuration
#   - aws_s3_bucket_logging
