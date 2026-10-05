"""
aws_state.py

Boto3-based AWS state collector -- AWS I/O ONLY. This module never
imports drift_engine.py, feature_extraction.py, or scenario_definitions.py,
and never decides what counts as "drift". Its only job is: call AWS,
return either a raw-response bundle or a clearly categorized error.
Converting that raw bundle into the project's normalized schema happens
in aws_normalizer.py (kept deliberately separate, per the milestone's
"keep AWS-specific code separate from the generic drift engine"
requirement -- this file is the AWS-specific half; drift_engine.py,
untouched, remains fully generic).

Credentials: NEVER hardcoded here. boto3.client(...) uses the default
credential resolution chain (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
AWS_SESSION_TOKEN environment variables, a ~/.aws/credentials profile, or
an attached IAM role) -- whatever the operator has configured locally.

Every "not configured" AWS state (no lifecycle rule, no bucket policy, no
public access block, versioning never touched) is a NORMAL, valid outcome
-- represented as None for that key, not an error. Only genuine problems
(bad/missing credentials, no network path to AWS, access denied, bucket
does not exist) raise AWSConfigurationError with a clear category, so the
caller can react appropriately instead of receiving a fabricated or
partial result.
"""

import json

import boto3
import botocore.exceptions


class AWSConfigurationError(Exception):
    """
    Raised for credential/connectivity/permission/existence problems that
    must stop the pipeline before any AWS data is trusted or normalized.
    """

    def __init__(self, category, message, original_exception=None):
        self.category = category  # see CATEGORY_* constants below
        self.message = message
        self.original_exception = original_exception
        super().__init__(message)


CATEGORY_NO_CREDENTIALS = "no_credentials"
CATEGORY_NETWORK_UNREACHABLE = "network_unreachable"
CATEGORY_ACCESS_DENIED = "access_denied"
CATEGORY_NOT_FOUND = "not_found"
CATEGORY_OTHER = "other"


def check_aws_credentials(region_name=None):
    """
    Lightweight, explicit credential/connectivity check via
    sts.get_caller_identity() -- the standard "am I even authenticated"
    probe. NEVER raises; always returns a result, since providing that
    result IS the point of this function.

    Returns: (ok: bool, message: str, identity: dict or None)
    """
    try:
        client = boto3.client("sts", region_name=region_name)
        identity = client.get_caller_identity()
        return (
            True,
            "AWS credentials are configured and valid.",
            {
                "account": identity.get("Account"),
                "arn": identity.get("Arn"),
                "user_id": identity.get("UserId"),
            },
        )
    except botocore.exceptions.NoCredentialsError:
        return (
            False,
            "No AWS credentials configured (checked environment variables, "
            "~/.aws/credentials, and an attached instance/role profile).",
            None,
        )
    except botocore.exceptions.EndpointConnectionError as e:
        return False, f"Could not reach the AWS STS endpoint (network/DNS issue): {e}", None
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        return False, f"AWS rejected the request (ClientError: {code}): {e}", None
    except Exception as e:
        # Deliberately broad: covers botocore.parsers.ResponseParserError
        # (observed in this project's own sandboxed dev environment as a
        # network-egress-proxy rejection -- see README) and any other
        # unexpected transport-level failure, without ever crashing the
        # caller or silently returning a fabricated "ok".
        return False, f"Unexpected error contacting AWS ({type(e).__name__}): {e}", None


def get_s3_client(region_name=None):
    """Thin wrapper so callers (and tests, via monkeypatching) have one
    place to construct the S3 client. No credentials are passed here --
    the default chain resolves them."""
    return boto3.client("s3", region_name=region_name)


def _is_error_code(exc, *codes):
    return (
        isinstance(exc, botocore.exceptions.ClientError)
        and exc.response.get("Error", {}).get("Code") in codes
    )


def fetch_s3_bucket_raw_config(client, bucket_name):
    """
    Calls the individual S3 config-getter APIs for one bucket and returns
    a raw-response bundle (plain dict of the AWS API responses, otherwise
    untouched). Does NOT normalize or interpret the data -- that is
    aws_normalizer.py's job.

    Raises AWSConfigurationError (not a bare exception) for genuine
    problems: bucket doesn't exist, access denied, no credentials, no
    network path to AWS. "Not configured" S3 states (no lifecycle rule,
    no bucket policy, no public access block) are normal and represented
    as None, never raised as errors.
    """
    try:
        client.head_bucket(Bucket=bucket_name)
    except botocore.exceptions.NoCredentialsError as e:
        raise AWSConfigurationError(CATEGORY_NO_CREDENTIALS, "No AWS credentials configured.", e)
    except botocore.exceptions.EndpointConnectionError as e:
        raise AWSConfigurationError(CATEGORY_NETWORK_UNREACHABLE, f"Could not reach the AWS S3 endpoint: {e}", e)
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        if code in ("404", "NoSuchBucket"):
            raise AWSConfigurationError(CATEGORY_NOT_FOUND, f"Bucket '{bucket_name}' does not exist or is not visible.", e)
        if code in ("403", "AccessDenied"):
            raise AWSConfigurationError(
                CATEGORY_ACCESS_DENIED,
                f"Access denied checking bucket '{bucket_name}'. "
                f"Required IAM permissions include s3:GetBucket*, s3:ListBucket, s3:GetEncryptionConfiguration.",
                e,
            )
        raise AWSConfigurationError(CATEGORY_OTHER, f"Unexpected error checking bucket '{bucket_name}': {e}", e)
    except Exception as e:
        raise AWSConfigurationError(CATEGORY_OTHER, f"Unexpected error ({type(e).__name__}) checking bucket '{bucket_name}': {e}", e)

    raw = {"bucket_name": bucket_name}

    # Public Access Block -- absence is a normal, valid AWS state.
    try:
        resp = client.get_public_access_block(Bucket=bucket_name)
        raw["public_access_block"] = resp["PublicAccessBlockConfiguration"]
    except botocore.exceptions.ClientError as e:
        if _is_error_code(e, "NoSuchPublicAccessBlockConfiguration"):
            raw["public_access_block"] = None
        else:
            raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching public access block: {e}", e)

    # ACL -- always present for an accessible bucket.
    try:
        raw["acl"] = client.get_bucket_acl(Bucket=bucket_name)
    except botocore.exceptions.ClientError as e:
        raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching bucket ACL: {e}", e)

    # Encryption -- absence is normal (encryption not configured).
    try:
        resp = client.get_bucket_encryption(Bucket=bucket_name)
        raw["encryption"] = resp["ServerSideEncryptionConfiguration"]
    except botocore.exceptions.ClientError as e:
        if _is_error_code(e, "ServerSideEncryptionConfigurationNotFoundError"):
            raw["encryption"] = None
        else:
            raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching bucket encryption: {e}", e)

    # Versioning -- response may simply lack a "Status" key if never touched.
    try:
        raw["versioning"] = client.get_bucket_versioning(Bucket=bucket_name)
    except botocore.exceptions.ClientError as e:
        raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching bucket versioning: {e}", e)

    # Logging -- response may simply lack a "LoggingEnabled" key.
    try:
        raw["logging"] = client.get_bucket_logging(Bucket=bucket_name)
    except botocore.exceptions.ClientError as e:
        raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching bucket logging: {e}", e)

    # Lifecycle -- absence is normal.
    try:
        resp = client.get_bucket_lifecycle_configuration(Bucket=bucket_name)
        raw["lifecycle"] = resp.get("Rules")
    except botocore.exceptions.ClientError as e:
        if _is_error_code(e, "NoSuchLifecycleConfiguration"):
            raw["lifecycle"] = None
        else:
            raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching lifecycle configuration: {e}", e)

    # Bucket policy -- absence is normal (bucket-owner-only access).
    try:
        resp = client.get_bucket_policy(Bucket=bucket_name)
        raw["policy"] = json.loads(resp["Policy"])
    except botocore.exceptions.ClientError as e:
        if _is_error_code(e, "NoSuchBucketPolicy"):
            raw["policy"] = None
        else:
            raise AWSConfigurationError(CATEGORY_OTHER, f"Error fetching bucket policy: {e}", e)

    return raw
