"""
sg_iam_collectors.py

Fetches live EC2 Security Group and IAM Role configuration with boto3 and
normalizes it into the SAME schema scenario_definitions.sg_baseline() /
iam_baseline() produce -- the field names feature_extraction's
ATTRIBUTE_KNOWLEDGE_BASE already has rules for. drift_engine and
feature_extraction stay untouched; all AWS-response-shape knowledge for
these two resource families lives here (mirrors aws_normalizer.py for S3).

Deliberate simplifications (documented, not hidden):
  Security group
    - inbound_ssh / inbound_rdp / inbound_https: the rule covering port
      22 / 3389 / 443. If several CIDRs are allowed, 0.0.0.0/0 wins (the
      worst case is what matters for risk); else the first CIDR.
    - internal_service_port: the rule covering the configured service
      port (default 5432). range = "single" when FromPort == ToPort, else
      "<from>-<to>".
    - inbound_custom: the first ingress rule not covering any of the
      above ports -> {"port", "source_cidr"}; None when absent.
    - peer_sg_reference: first referenced security group id in any
      ingress rule; None when absent.
    - outbound_default: the all-traffic egress rule's destination CIDR.
  IAM role
    - trust_principal / requires_mfa from the first AssumeRole statement
      of the trust policy (requires_mfa = aws:MultiFactorAuthPresent
      condition present and "true").
    - actions / resources / effect from the role's single inline policy
      (first statement). Actions and resources are sorted lists.
    - permissions_boundary: boundary ARN or None.
    - group_membership: roles cannot belong to IAM groups, so this is
      always None for a role (compares equal in desired and actual).
"""

import json
import urllib.parse
from typing import Any, Dict, List, Optional

PUBLIC_CIDR = "0.0.0.0/0"


# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------

def _covers(rule: Dict[str, Any], port: int) -> bool:
    if rule.get("IpProtocol") == "-1":
        return True
    lo, hi = rule.get("FromPort"), rule.get("ToPort")
    return lo is not None and hi is not None and lo <= port <= hi


def _cidrs(rule: Dict[str, Any]) -> List[str]:
    return [r["CidrIp"] for r in rule.get("IpRanges", []) if "CidrIp" in r]


def _worst_cidr(cidrs: List[str]) -> Optional[str]:
    if not cidrs:
        return None
    return PUBLIC_CIDR if PUBLIC_CIDR in cidrs else cidrs[0]


def normalize_security_group(sg: Dict[str, Any], service_port: int = 5432) -> Dict[str, Any]:
    """sg is one element of ec2.describe_security_groups()["SecurityGroups"]."""
    ingress = sg.get("IpPermissions", [])
    egress = sg.get("IpPermissionsEgress", [])

    def port_rule(port: int) -> Optional[Dict[str, Any]]:
        cidrs = [c for r in ingress if r.get("IpProtocol") != "-1" and _covers(r, port) for c in _cidrs(r)]
        source = _worst_cidr(cidrs)
        return {"port": port, "source_cidr": source} if source else None

    service_rule = None
    for r in ingress:
        if r.get("IpProtocol") != "-1" and _covers(r, service_port) and _cidrs(r):
            lo, hi = r["FromPort"], r["ToPort"]
            service_rule = {"port": service_port, "range": "single" if lo == hi else f"{lo}-{hi}"}
            break

    known_ports = (22, 3389, 443, service_port)
    inbound_custom = None
    for r in ingress:
        if not _cidrs(r):
            continue
        if r.get("IpProtocol") == "-1" or not any(_covers(r, p) for p in known_ports):
            inbound_custom = {"port": r.get("FromPort", "all"), "source_cidr": _worst_cidr(_cidrs(r))}
            break

    peer = None
    for r in ingress:
        pairs = r.get("UserIdGroupPairs", [])
        if pairs:
            peer = pairs[0].get("GroupId")
            break

    outbound = None
    for r in egress:
        if r.get("IpProtocol") == "-1":
            outbound = {"port": "all", "destination_cidr": _worst_cidr(_cidrs(r))}
            break

    return {
        "resource_type": "aws_security_group",
        "sg_id": sg["GroupId"],
        "instance_name": sg.get("GroupName"),
        "inbound_ssh": port_rule(22),
        "inbound_rdp": port_rule(3389),
        "inbound_https": port_rule(443),
        "inbound_custom": inbound_custom,
        "outbound_default": outbound,
        "internal_service_port": service_rule,
        "peer_sg_reference": peer,
    }


def fetch_security_group(ec2_client, group_id: str) -> Dict[str, Any]:
    resp = ec2_client.describe_security_groups(GroupIds=[group_id])
    return resp["SecurityGroups"][0]


# ---------------------------------------------------------------------------
# IAM roles
# ---------------------------------------------------------------------------

def _as_list(v: Any) -> List[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _decode_policy(doc: Any) -> Dict[str, Any]:
    """boto3 returns policy documents already decoded as dicts; raw API /
    some mocks return URL-encoded JSON strings. Accept both."""
    if isinstance(doc, dict):
        return doc
    return json.loads(urllib.parse.unquote(doc))


def normalize_iam_role(role: Dict[str, Any], inline_policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    trust = _decode_policy(role["AssumeRolePolicyDocument"])
    trust_stmt = _as_list(trust.get("Statement"))[0]
    principal = trust_stmt.get("Principal", {})
    trust_principal = principal.get("AWS") if isinstance(principal, dict) else principal
    if isinstance(trust_principal, list):
        trust_principal = sorted(trust_principal)[0]
    mfa_flag = (
        trust_stmt.get("Condition", {}).get("Bool", {}).get("aws:MultiFactorAuthPresent")
    )
    requires_mfa = str(mfa_flag).lower() == "true"

    actions: List[str] = []
    resources: List[str] = []
    effect = None
    if inline_policy is not None:
        stmt = _as_list(inline_policy.get("Statement"))[0]
        actions = sorted(_as_list(stmt.get("Action")))
        resources = sorted(_as_list(stmt.get("Resource")))
        effect = stmt.get("Effect")

    boundary = role.get("PermissionsBoundary", {}).get("PermissionsBoundaryArn")

    return {
        "resource_type": "aws_iam_entity",
        "entity_name": role["RoleName"],
        "actions": actions,
        "resources": resources,
        "effect": effect,
        "requires_mfa": requires_mfa,
        "trust_principal": trust_principal,
        "permissions_boundary": boundary,
        "group_membership": None,
    }


def fetch_iam_role(iam_client, role_name: str):
    """Returns (role, inline_policy_document_or_None)."""
    role = iam_client.get_role(RoleName=role_name)["Role"]
    names = iam_client.list_role_policies(RoleName=role_name).get("PolicyNames", [])
    policy = None
    if names:
        doc = iam_client.get_role_policy(RoleName=role_name, PolicyName=sorted(names)[0])["PolicyDocument"]
        policy = _decode_policy(doc)
    return role, policy
