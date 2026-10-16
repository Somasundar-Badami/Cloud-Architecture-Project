"""
compliance.py

Maps every drift attribute the model knows about to the compliance
controls it violates, so the dashboard can say *which rule* a drift
breaks, not just how risky it is.

Two control catalogues are used:
  - CIS Amazon Web Services Foundations Benchmark v1.4.0 ("cis")
  - AWS Security Hub Foundational Security Best Practices ("security_hub")

Not every attribute has a CIS control: the CIS benchmark only covers a
foundational subset of AWS. Where CIS has no control, "cis" is None and
the Security Hub control (if any) carries the mapping instead. A mapping
is marked "direct" when the drift itself is what the control checks for
and "related" when the drift weakens something the control relies on.

No Streamlit calls in here, so it is unit-testable.
"""

from typing import Any, Dict, Iterable, List, Optional

CIS_BENCHMARK = "CIS AWS Foundations Benchmark v1.4.0"

# attribute -> mapping. Keys are the attribute paths used by
# feature_extraction.ATTRIBUTE_KNOWLEDGE_BASE.
CONTROL_MAP: Dict[str, Dict[str, Any]] = {
    # --- S3 ---
    "block_public_access": {
        "cis": "2.1.5", "match": "direct", "security_hub": ["S3.1", "S3.8"],
        "title": "S3 buckets must have Block Public Access enabled",
    },
    "acl": {
        "cis": "2.1.5", "match": "related", "security_hub": ["S3.2", "S3.3"],
        "title": "S3 buckets must not allow public read or write access",
    },
    "encryption.enabled": {
        "cis": "2.1.1", "match": "direct", "security_hub": ["S3.4"],
        "title": "S3 buckets must use encryption at rest",
    },
    "bucket_policy_principal": {
        "cis": "2.1.5", "match": "related", "security_hub": ["S3.2", "S3.6"],
        "title": "S3 bucket policies must not grant access to every principal",
    },
    "versioning": {
        "cis": "2.1.3", "match": "related", "security_hub": ["S3.14"],
        "title": "S3 buckets should keep versioning (required for MFA Delete)",
    },
    "logging": {
        "cis": "3.6", "match": "related", "security_hub": ["S3.9"],
        "title": "S3 server access logging should be enabled",
    },
    "lifecycle_rule": {
        "cis": None, "match": "related", "security_hub": ["S3.13"],
        "title": "S3 buckets should have lifecycle configurations",
    },
    # --- EC2 security groups ---
    "inbound_ssh.source_cidr": {
        "cis": "5.2", "match": "direct", "security_hub": ["EC2.13"],
        "title": "Security groups must not allow SSH (22) from 0.0.0.0/0",
    },
    "inbound_rdp.source_cidr": {
        "cis": "5.2", "match": "direct", "security_hub": ["EC2.14"],
        "title": "Security groups must not allow RDP (3389) from 0.0.0.0/0",
    },
    "inbound_custom": {
        "cis": None, "match": "direct", "security_hub": ["EC2.18"],
        "title": "Only authorised ports may accept unrestricted inbound traffic",
    },
    "outbound_default.destination_cidr": {
        "cis": "5.3", "match": "related", "security_hub": ["EC2.2"],
        "title": "Security group egress should follow least privilege",
    },
    "internal_service_port.range": {
        "cis": None, "match": "related", "security_hub": ["EC2.18"],
        "title": "Open port ranges should be limited to what the service needs",
    },
    "peer_sg_reference": {
        "cis": None, "match": "related", "security_hub": [],
        "title": "Cross-security-group access should be declared in IaC",
    },
    # --- IAM ---
    "actions": {
        "cis": "1.16", "match": "direct", "security_hub": ["IAM.1"],
        "title": "IAM policies must not grant full '*:*' administrative privileges",
    },
    "resources": {
        "cis": "1.16", "match": "direct", "security_hub": ["IAM.1"],
        "title": "IAM policies must not grant full '*:*' administrative privileges",
    },
    "trust_principal": {
        "cis": None, "match": "related", "security_hub": [],
        "title": "Role trust policies should only trust known accounts",
    },
    "requires_mfa": {
        "cis": "1.10", "match": "related", "security_hub": ["IAM.5"],
        "title": "MFA should be required for privileged access",
    },
    "effect": {
        "cis": "1.16", "match": "related", "security_hub": ["IAM.1"],
        "title": "Explicit Deny statements must not be weakened to Allow",
    },
    "group_membership": {
        "cis": "1.15", "match": "related", "security_hub": ["IAM.2"],
        "title": "IAM permissions should come from reviewed group membership",
    },
    "permissions_boundary": {
        "cis": None, "match": "related", "security_hub": [],
        "title": "Permissions boundaries must stay attached to delegated roles",
    },
    "access_key_count": {
        "cis": "1.13", "match": "direct", "security_hub": ["IAM.3"],
        "title": "Each IAM user should have at most one active access key",
    },
}


def controls_for_attribute(attribute: str) -> Optional[Dict[str, Any]]:
    """Returns the control mapping for one attribute path, or None when the
    attribute is not in the model's schema (the same 'Review' case the
    detector Lambda uses)."""
    mapping = CONTROL_MAP.get(attribute)
    if mapping is None:
        return None
    return {"attribute": attribute, **mapping}


def compliance_rows(changes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Turns a drift_engine change list into one table row per changed
    attribute, ready for st.dataframe. Unknown attributes still get a row
    so nothing silently disappears from the table.
    """
    rows = []
    for change in changes:
        attribute = change["attribute"]
        mapping = controls_for_attribute(attribute)
        if mapping is None:
            rows.append({"attribute": attribute, "cis_control": "—", "security_hub": "—",
                         "match": "unmapped", "rule": "Not in the model schema; review by hand"})
            continue
        rows.append({
            "attribute": attribute,
            "cis_control": f"CIS {mapping['cis']}" if mapping["cis"] else "—",
            "security_hub": ", ".join(mapping["security_hub"]) or "—",
            "match": mapping["match"],
            "rule": mapping["title"],
        })
    return rows


def violated_cis_controls(changes: Iterable[Dict[str, Any]]) -> List[str]:
    """Sorted, de-duplicated CIS control ids a change list violates."""
    ids = {CONTROL_MAP[c["attribute"]]["cis"] for c in changes
           if c["attribute"] in CONTROL_MAP and CONTROL_MAP[c["attribute"]]["cis"]}
    return sorted(ids, key=lambda s: [int(p) for p in s.split(".")])
