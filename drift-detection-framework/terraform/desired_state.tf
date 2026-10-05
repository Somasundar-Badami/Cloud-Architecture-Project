# desired_state.tf
#
# Publishes the Terraform-declared DESIRED STATE of the three monitored
# resources to S3 as one JSON document, in the normalized schema that
# src/aws_normalizer.py produces from live AWS responses. The detector
# Lambda diffs live state against this document.
#
# The artifacts bucket is private, encrypted and has public access blocked.

resource "aws_s3_bucket" "artifacts" {
  bucket        = "${local.name_prefix}-artifacts-${random_id.bucket_suffix.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

locals {
  desired_state_key = "desired-state/desired_state.json"

  desired_state_document = {
    generated_by = "terraform"
    resources = [
      {
        resource_id = "s3:${aws_s3_bucket.demo.bucket}"
        kind        = "s3_bucket"
        desired = {
          resource_type = "aws_s3_bucket"
          bucket_name   = aws_s3_bucket.demo.bucket
          block_public_access = alltrue([
            aws_s3_bucket_public_access_block.demo.block_public_acls,
            aws_s3_bucket_public_access_block.demo.ignore_public_acls,
            aws_s3_bucket_public_access_block.demo.block_public_policy,
            aws_s3_bucket_public_access_block.demo.restrict_public_buckets,
          ])
          acl = aws_s3_bucket_acl.demo.acl
          # main.tf uses SSE-S3 (AES256), which has no KMS key
          encryption = { enabled = true, kms_key_id = null }
          versioning = lower(one(aws_s3_bucket_versioning.demo.versioning_configuration).status) == "enabled" ? "enabled" : "disabled"
          # main.tf deliberately declares no logging, lifecycle rule or bucket
          # policy; owner-only access normalizes to this placeholder principal
          logging                 = "disabled"
          lifecycle_rule          = null
          bucket_policy_principal = "arn:aws:iam::000000000000:root"
        }
      },
      {
        resource_id = "sg:${aws_security_group.demo.id}"
        kind        = "security_group"
        desired = {
          resource_type         = "aws_security_group"
          sg_id                 = aws_security_group.demo.id
          instance_name         = local.sg_name
          inbound_ssh           = { port = 22, source_cidr = local.sg_internal_cidr }
          inbound_rdp           = { port = 3389, source_cidr = local.sg_internal_cidr }
          inbound_https         = { port = 443, source_cidr = local.sg_public_cidr }
          inbound_custom        = null
          outbound_default      = { port = "all", destination_cidr = local.sg_internal_cidr }
          internal_service_port = { port = local.sg_internal_service, range = "single" }
          peer_sg_reference     = null
        }
      },
      {
        resource_id        = "iam:${aws_iam_role.demo.name}"
        kind               = "iam_policy"
        inline_policy_name = aws_iam_role_policy.demo.name
        desired = {
          resource_type        = "aws_iam_entity"
          entity_name          = aws_iam_role.demo.name
          actions              = sort(local.iam_primary_actions)
          resources            = sort(local.iam_primary_resources)
          effect               = "Allow"
          requires_mfa         = true
          trust_principal      = local.iam_trust_principal
          permissions_boundary = aws_iam_policy.boundary.arn
          group_membership     = "StandardAccess"
        }
      },
    ]
  }
}

resource "aws_s3_object" "desired_state" {
  bucket       = aws_s3_bucket.artifacts.id
  key          = local.desired_state_key
  content      = jsonencode(local.desired_state_document)
  content_type = "application/json"
}
