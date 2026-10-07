"""
aws_normalizer.py

Converts (a) raw boto3 S3 API responses and (b) the project's Terraform
configuration into the SAME normalized schema already used throughout
this project -- the exact field set scenario_definitions.s3_baseline()
produces and feature_extraction.ATTRIBUTE_KNOWLEDGE_BASE already has
rules for (block_public_access, acl, encryption.enabled,
bucket_policy_principal, versioning, logging, lifecycle_rule).

This is the ONLY place AWS-response-shape knowledge lives. drift_engine.py
is untouched and stays completely generic (it just diffs two dicts);
feature_extraction.py is untouched (it already knows how to interpret
these exact field names/values, since they're the same ones the synthetic
dataset uses).

Deliberate simplifications (real AWS config is richer than this project's
9-feature schema was ever designed to capture -- documented here, not
hidden):
  - block_public_access is a single bool, collapsed from AWS's actual
    4-setting PublicAccessBlockConfiguration (True only if ALL FOUR
    sub-settings are true -- mirrors the AWS console's single "Block all
    public access" master toggle).
  - acl is "public-read" or "private" only, collapsed from AWS's full
    grant-based ACL model (checks for an AllUsers-group grant with READ
    or FULL_CONTROL; does not distinguish public-read-write, authenticated-
    users-only grants, or fine-grained per-permission nuance).
  - bucket_policy_principal is "*" or a single placeholder non-wildcard
    string, collapsed from AWS's full arbitrary-JSON policy documents.
"""

import os
from typing import Any, Dict, List, Optional

PUBLIC_ACL_GROUP_URI = "http://acs.amazonaws.com/groups/global/AllUsers"


# ---------------------------------------------------------------------------
# Actual-state normalization (raw boto3 responses -> normalized schema)
# ---------------------------------------------------------------------------

def _public_access_block_to_bool(pab: Optional[Dict[str, Any]]) -> bool:
    """True only if ALL FOUR sub-settings are true (fully blocked). A
    missing PublicAccessBlockConfiguration (None) means nothing is
    blocked at this layer -> False, same as if all four were false."""
    if pab is None:
        return False
    return bool(
        pab.get("BlockPublicAcls", False)
        and pab.get("IgnorePublicAcls", False)
        and pab.get("BlockPublicPolicy", False)
        and pab.get("RestrictPublicBuckets", False)
    )


def _acl_response_to_string(acl_response: Dict[str, Any]) -> str:
    """Inspects get_bucket_acl()'s Grants list for an AllUsers-group grant
    with READ or FULL_CONTROL -> "public-read"; otherwise "private"."""
    for grant in acl_response.get("Grants", []):
        grantee = grant.get("Grantee", {})
        if grantee.get("URI") == PUBLIC_ACL_GROUP_URI and grant.get("Permission") in ("READ", "FULL_CONTROL"):
            return "public-read"
    return "private"


def _encryption_to_dict(encryption_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if encryption_config is None:
        return {"enabled": False, "kms_key_id": None}
    rules = encryption_config.get("Rules", [])
    if not rules:
        return {"enabled": False, "kms_key_id": None}
    default = rules[0].get("ApplyServerSideEncryptionByDefault", {})
    kms_key_id = default.get("KMSMasterKeyID")  # None for plain AES256
    return {"enabled": True, "kms_key_id": kms_key_id}


def _versioning_to_string(versioning_response: Dict[str, Any]) -> str:
    return "enabled" if versioning_response.get("Status") == "Enabled" else "disabled"


def _logging_to_string(logging_response: Dict[str, Any]) -> str:
    return "enabled" if "LoggingEnabled" in logging_response else "disabled"


def _lifecycle_to_dict(rules: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    if not rules:
        return None
    rule = rules[0]
    retention_days = rule.get("Expiration", {}).get("Days")
    return {"enabled": rule.get("Status") == "Enabled", "retention_days": retention_days}


def _policy_to_principal_string(policy: Optional[Dict[str, Any]], account_id: Optional[str], bucket_name: str) -> str:
    """Returns "*" if any statement grants a wildcard principal;
    otherwise a placeholder non-wildcard principal representing
    "bucket-owner-only access" (no policy attached is the normal case for
    this project's demo bucket)."""
    if policy is None:
        account = account_id or "000000000000"
        return f"arn:aws:iam::{account}:root"
    for statement in policy.get("Statement", []):
        principal = statement.get("Principal")
        if principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*"):
            return "*"
    account = account_id or "000000000000"
    return f"arn:aws:iam::{account}:root"


def normalize_s3_actual_state(raw: Dict[str, Any], account_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Converts the raw bundle returned by aws_state.fetch_s3_bucket_raw_config()
    into the project's normalized S3 schema -- the same shape
    scenario_definitions.s3_baseline() produces.
    """
    return {
        "resource_type": "aws_s3_bucket",
        "bucket_name": raw["bucket_name"],
        "block_public_access": _public_access_block_to_bool(raw.get("public_access_block")),
        "acl": _acl_response_to_string(raw["acl"]),
        "encryption": _encryption_to_dict(raw.get("encryption")),
        "versioning": _versioning_to_string(raw["versioning"]),
        "logging": _logging_to_string(raw["logging"]),
        "lifecycle_rule": _lifecycle_to_dict(raw.get("lifecycle")),
        "bucket_policy_principal": _policy_to_principal_string(raw.get("policy"), account_id, raw["bucket_name"]),
    }


# ---------------------------------------------------------------------------
# Desired-state normalization (parsed Terraform config -> normalized schema)
# ---------------------------------------------------------------------------

def _clean_hcl(obj: Any) -> Any:
    """
    python-hcl2 (this project's installed version, 8.1.4) emits string
    literals and resource-type/name keys with the original HCL quote
    characters still embedded (e.g. the dict key '"aws_s3_bucket"' rather
    than 'aws_s3_bucket', and the value '"AES256"' rather than 'AES256').
    This recursively strips those artifacts and drops the library's
    internal '__is_block__' marker key. Verified against this project's
    actual terraform/*.tf files during development (see
    tests/test_aws_state.py) -- if a future hcl2 version changes this
    behavior, that test will fail loudly rather than silently misparsing.
    """
    if isinstance(obj, str):
        return obj.strip('"')
    if isinstance(obj, dict):
        return {_clean_hcl(k): _clean_hcl(v) for k, v in obj.items() if k != "__is_block__"}
    if isinstance(obj, list):
        return [_clean_hcl(x) for x in obj]
    return obj


def load_terraform_resources(tf_dir: str) -> Dict[str, Dict[str, Any]]:
    """
    Parses every *.tf file in tf_dir and returns a flat lookup:
        {"<resource_type>.<resource_name>": {attrs...}}
    e.g. {"aws_s3_bucket_versioning.demo": {"status_from_versioning_configuration": "Disabled", ...}}
    """
    import hcl2  # lazy: only needed for local Terraform parsing, not inside Lambda

    resources: Dict[str, Dict[str, Any]] = {}
    for filename in sorted(os.listdir(tf_dir)):
        if not filename.endswith(".tf"):
            continue
        with open(os.path.join(tf_dir, filename)) as f:
            parsed = hcl2.load(f)
        parsed = _clean_hcl(parsed)
        for resource_block in parsed.get("resource", []):
            for resource_type, named in resource_block.items():
                for resource_name, attrs in named.items():
                    resources[f"{resource_type}.{resource_name}"] = attrs
    return resources


def derive_s3_desired_state_from_terraform(tf_dir: str, bucket_name: str, account_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses the ACTUAL terraform/*.tf files (not a hand-maintained parallel
    copy) and derives the normalized desired state for the demo S3 bucket.
    bucket_name is supplied by the caller (e.g. from `terraform output
    bucket_name`) since it includes a random suffix only known after
    `terraform apply`, which static HCL parsing cannot resolve.
    """
    resources = load_terraform_resources(tf_dir)

    pab = resources.get("aws_s3_bucket_public_access_block.demo")
    block_public_access = bool(
        pab
        and pab.get("block_public_acls")
        and pab.get("ignore_public_acls")
        and pab.get("block_public_policy")
        and pab.get("restrict_public_buckets")
    )

    acl_resource = resources.get("aws_s3_bucket_acl.demo")
    acl = acl_resource.get("acl", "private") if acl_resource else "private"

    enc_resource = resources.get("aws_s3_bucket_server_side_encryption_configuration.demo")
    encryption_enabled = False
    kms_key_id = None
    if enc_resource:
        rules = enc_resource.get("rule", [])
        if rules:
            default = rules[0].get("apply_server_side_encryption_by_default", [])
            if default:
                encryption_enabled = True
                kms_key_id = default[0].get("kms_master_key_id")

    versioning_resource = resources.get("aws_s3_bucket_versioning.demo")
    versioning = "disabled"
    if versioning_resource:
        vc = versioning_resource.get("versioning_configuration", [])
        if vc and vc[0].get("status") == "Enabled":
            versioning = "enabled"

    logging = "enabled" if "aws_s3_bucket_logging.demo" in resources else "disabled"

    lifecycle_resource = resources.get("aws_s3_bucket_lifecycle_configuration.demo")
    lifecycle_rule = None  # main.tf declares no lifecycle resource -> None, matching S7's "deleted" representation
    if lifecycle_resource:
        lifecycle_rule = {"enabled": True, "retention_days": None}  # placeholder if ever added

    # Same placeholder rule as _policy_to_principal_string() so a real
    # account's "no policy" state compares equal instead of showing as drift.
    bucket_policy_principal = (
        "*" if "aws_s3_bucket_policy.demo" in resources else f"arn:aws:iam::{account_id or '000000000000'}:root"
    )

    return {
        "resource_type": "aws_s3_bucket",
        "bucket_name": bucket_name,
        "block_public_access": block_public_access,
        "acl": acl,
        "encryption": {"enabled": encryption_enabled, "kms_key_id": kms_key_id},
        "versioning": versioning,
        "logging": logging,
        "lifecycle_rule": lifecycle_rule,
        "bucket_policy_principal": bucket_policy_principal,
    }
