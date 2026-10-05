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
    import hcl2  # local-only dependency; not needed (or packaged) in AWS Lambda

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


def derive_s3_desired_state_from_terraform(tf_dir: str, bucket_name: str) -> Dict[str, Any]:
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

    bucket_policy_principal = (
        "*" if "aws_s3_bucket_policy.demo" in resources else "arn:aws:iam::000000000000:root"
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


# ---------------------------------------------------------------------------
# Phase 2: EC2 Security Group (describe_security_groups -> normalized schema)
#
# The normalized SG schema (scenario_definitions.sg_baseline) has one slot
# per *role* a rule plays, not one entry per AWS rule. Real rules are
# assigned to those slots as follows (documented simplifications):
#   inbound_ssh / inbound_rdp / inbound_https -- any inbound rule whose port
#       range covers 22 / 3389 / 443. If several CIDRs reach that port, a
#       public one (0.0.0.0/0 or ::/0) wins, otherwise the lowest CIDR.
#   internal_service_port -- the inbound rule from a NON-public CIDR that
#       covers the declared internal service port (e.g. 5432); "range" is
#       "single" if it covers exactly that port, else "<from>-<to>".
#   inbound_custom -- any other inbound CIDR rule (public preferred), or None.
#   outbound_default -- egress destination (public preferred), or None.
#   peer_sg_reference -- lowest referenced source security group id, or None.
# ---------------------------------------------------------------------------

PUBLIC_CIDR = "0.0.0.0/0"
_PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}
_NAMED_PORTS = {22: "inbound_ssh", 3389: "inbound_rdp", 443: "inbound_https"}


def _expand_permissions(permissions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One entry per (port range, CIDR). Protocol -1 ("all traffic") covers
    every port; IPv6 ::/0 is treated the same as 0.0.0.0/0."""
    entries = []
    for perm in permissions:
        all_ports = perm.get("IpProtocol") == "-1" or "FromPort" not in perm
        from_port = 0 if all_ports else perm["FromPort"]
        to_port = 65535 if all_ports else perm["ToPort"]
        cidrs = [r["CidrIp"] for r in perm.get("IpRanges", [])]
        cidrs += [r["CidrIpv6"] for r in perm.get("Ipv6Ranges", [])]
        for cidr in cidrs:
            entries.append({
                "from": from_port,
                "to": to_port,
                "all_ports": all_ports,
                "cidr": PUBLIC_CIDR if cidr in _PUBLIC_CIDRS else cidr,
            })
    return entries


def _pick_cidr(cidrs: List[str]) -> str:
    return PUBLIC_CIDR if PUBLIC_CIDR in cidrs else sorted(cidrs)[0]


def normalize_sg_actual_state(security_group: Dict[str, Any], instance_name: str,
                              internal_service_port: int) -> Dict[str, Any]:
    """
    security_group: one element of ec2.describe_security_groups()["SecurityGroups"].
    instance_name / internal_service_port: identity + intent from the desired
    state (AWS has no notion of "the internal service port").
    """
    inbound = _expand_permissions(security_group.get("IpPermissions", []))
    outbound = _expand_permissions(security_group.get("IpPermissionsEgress", []))
    used = set()

    state: Dict[str, Any] = {
        "resource_type": "aws_security_group",
        "sg_id": security_group["GroupId"],
        "instance_name": instance_name,
    }

    for port, slot in _NAMED_PORTS.items():
        covering = [i for i, e in enumerate(inbound) if e["from"] <= port <= e["to"]]
        exact = [i for i in covering if inbound[i]["from"] == inbound[i]["to"] == port]
        used.update(exact)
        state[slot] = (
            {"port": port, "source_cidr": _pick_cidr([inbound[i]["cidr"] for i in covering])}
            if covering else None
        )

    internal = [
        i for i, e in enumerate(inbound)
        if e["cidr"] != PUBLIC_CIDR and not e["all_ports"] and e["from"] <= internal_service_port <= e["to"]
        and i not in used
    ]
    if internal:
        widest = max(internal, key=lambda i: inbound[i]["to"] - inbound[i]["from"])
        used.update(internal)  # a narrower duplicate is not a separate "custom" rule
        e = inbound[widest]
        state["internal_service_port"] = {
            "port": internal_service_port,
            "range": "single" if e["from"] == e["to"] else f"{e['from']}-{e['to']}",
        }
    else:
        state["internal_service_port"] = None

    leftovers = [e for i, e in enumerate(inbound) if i not in used]
    if leftovers:
        public = [e for e in leftovers if e["cidr"] == PUBLIC_CIDR]
        chosen = public[0] if public else sorted(leftovers, key=lambda e: (e["from"], e["cidr"]))[0]
        state["inbound_custom"] = {
            "port": "all" if chosen["all_ports"] else chosen["from"],
            "source_cidr": chosen["cidr"],
        }
    else:
        state["inbound_custom"] = None

    state["outbound_default"] = (
        {"port": "all", "destination_cidr": _pick_cidr([e["cidr"] for e in outbound])}
        if outbound else None
    )

    peers = sorted(
        pair["GroupId"]
        for perm in security_group.get("IpPermissions", [])
        for pair in perm.get("UserIdGroupPairs", [])
    )
    state["peer_sg_reference"] = peers[0] if peers else None
    return state


# ---------------------------------------------------------------------------
# Phase 2: IAM role (get_role + get_role_policy + attached policies ->
# normalized schema of scenario_definitions.iam_baseline)
#
# Documented simplifications:
#   actions / resources / effect / requires_mfa come from ONE statement of
#       the role's inline policy (Sid "PrimaryAccess", else the first one).
#   trust_principal -- first AWS principal of the trust policy (sorted), or
#       "service:<name>" for a service principal.
#   group_membership -- roles cannot join IAM groups, so the role analogue
#       of scenario I5 is used: "AdminGroup" when the AWS-managed
#       AdministratorAccess policy is attached, otherwise "StandardAccess".
# ---------------------------------------------------------------------------

ADMIN_POLICY_ARN = "arn:aws:iam::aws:policy/AdministratorAccess"
PRIMARY_STATEMENT_SID = "PrimaryAccess"


def _as_sorted_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return sorted(value)


def _requires_mfa(condition: Optional[Dict[str, Any]]) -> bool:
    for operator in ("Bool", "BoolIfExists"):
        value = (condition or {}).get(operator, {}).get("aws:MultiFactorAuthPresent")
        if value in ("true", True, ["true"]):
            return True
    return False


def _trust_principal(trust_policy: Dict[str, Any]) -> Optional[str]:
    for statement in trust_policy.get("Statement", []):
        principal = statement.get("Principal", {})
        if isinstance(principal, str):
            return principal
        if "AWS" in principal:
            return _as_sorted_list(principal["AWS"])[0]
        if "Service" in principal:
            return f"service:{_as_sorted_list(principal['Service'])[0]}"
    return None


def normalize_iam_role_actual_state(raw: Dict[str, Any]) -> Dict[str, Any]:
    """raw: bundle returned by aws_state.fetch_iam_role_raw_config()."""
    role = raw["role"]
    policy = raw.get("inline_policy") or {"Statement": []}
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    primary = next((s for s in statements if s.get("Sid") == PRIMARY_STATEMENT_SID), None)
    if primary is None and statements:
        primary = statements[0]
    primary = primary or {}

    boundary = role.get("PermissionsBoundary") or {}
    return {
        "resource_type": "aws_iam_entity",
        "entity_name": role["RoleName"],
        "actions": _as_sorted_list(primary.get("Action")),
        "resources": _as_sorted_list(primary.get("Resource")),
        "effect": primary.get("Effect"),
        "requires_mfa": _requires_mfa(primary.get("Condition")),
        "trust_principal": _trust_principal(role.get("AssumeRolePolicyDocument", {})),
        "permissions_boundary": boundary.get("PermissionsBoundaryArn"),
        "group_membership": "AdminGroup" if ADMIN_POLICY_ARN in raw.get("attached_policy_arns", []) else "StandardAccess",
    }
