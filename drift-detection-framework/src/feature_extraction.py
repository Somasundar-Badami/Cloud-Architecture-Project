"""
feature_extraction.py

Converts drift_engine.py output into the approved ML feature set:

    resource_type, changed_attribute, security_sensitivity, public_exposure,
    encryption_change, privilege_change, port_exposure, change_magnitude,
    drift_frequency

Design principle (per frozen implementation spec, Section 4):
    old_value / new_value are NEVER stored in the returned feature dict.
    They are only read *internally*, transiently, to decide the direction
    of a change (e.g. "did block_public_access go True -> False, or the
    other way around?"). Once that direction is turned into a boolean/
    categorical flag, the raw values are discarded.

How it works:
    1. A small "attribute knowledge base" (ATTRIBUTE_KNOWLEDGE_BASE) maps
       each known attribute path (e.g. "block_public_access",
       "encryption.enabled") to:
         - which resource type it belongs to
         - its intrinsic security_sensitivity (Low/Medium/High)
         - a small rule function that looks at (old_value, new_value) and
           decides public_exposure / encryption_change / privilege_change /
           port_exposure / change_magnitude for THAT SPECIFIC change.
    2. detect_drift() (from drift_engine.py) tells us WHICH attributes
       changed and what their old/new values were.
    3. extract_features() walks each changed attribute, looks up its rule,
       and combines the results into one record-level feature row.
       - Boolean flags are combined with OR (if ANY changed attribute
         triggers public_exposure, the whole record is public_exposure=True)
       - Severity-like fields (security_sensitivity, change_magnitude) are
         combined by taking the MAX severity across all changed attributes
       - port_exposure is combined so that public (0.0.0.0/0) beats
         internal, which beats none
    4. drift_frequency is NOT derivable from a single state comparison
       (it is a historical count), so it is passed in by the caller.

This keeps the mapping deterministic and traceable: every feature value
can be explained by pointing at the specific rule function that produced
it, rather than a black-box heuristic.
"""

from typing import Any, Dict, List, Tuple, Callable, Optional

from drift_engine import detect_drift

PUBLIC_CIDR = "0.0.0.0/0"

# Ordinal ordering used to combine severity-like fields across multiple
# simultaneous changes (e.g. IAM scenario I1 changes both "actions" and
# "resources" at once -> take the higher of the two).
SEVERITY_ORDER = {"None": 0, "Low": 1, "Medium": 2, "High": 3}


def _max_severity(a: str, b: str) -> str:
    return a if SEVERITY_ORDER[a] >= SEVERITY_ORDER[b] else b


# ---------------------------------------------------------------------------
# Per-attribute rule functions.
# Each takes (old_value, new_value) for ONE changed attribute and returns
# the flags that attribute contributes. Only booleans/categories are
# returned -- old_value/new_value never leave these functions.
# ---------------------------------------------------------------------------

def _rule_block_public_access(old: Any, new: Any) -> Dict[str, Any]:
    became_public = old is True and new is False
    return {
        "public_exposure": became_public,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": "none",
        "change_magnitude": "High" if became_public else "Low",
    }


def _rule_acl(old: Any, new: Any) -> Dict[str, Any]:
    became_public = new == "public-read" and old != "public-read"
    return {
        "public_exposure": became_public,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": "none",
        "change_magnitude": "High" if became_public else "Medium",
    }


def _rule_encryption_enabled(old: Any, new: Any) -> Dict[str, Any]:
    weakened = old is True and new is False
    return {
        "public_exposure": False,
        "encryption_change": weakened,
        "privilege_change": False,
        "port_exposure": "none",
        "change_magnitude": "Medium" if weakened else "Low",
    }


def _rule_bucket_policy_principal(old: Any, new: Any) -> Dict[str, Any]:
    became_wildcard = new == "*" and old != "*"
    return {
        "public_exposure": became_wildcard,
        "encryption_change": False,
        "privilege_change": became_wildcard,
        "port_exposure": "none",
        "change_magnitude": "High" if became_wildcard else "Medium",
    }


def _rule_low_impact_toggle(old: Any, new: Any) -> Dict[str, Any]:
    """Shared by S3 versioning/logging: operational settings, no exposure
    or privilege implications, always Low magnitude regardless of direction."""
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": "none",
        "change_magnitude": "Low",
    }


def _rule_inbound_cidr_generic(old: Any, new: Any) -> Dict[str, Any]:
    """Used for inbound_ssh.source_cidr and inbound_rdp.source_cidr."""
    opened_to_internet = new == PUBLIC_CIDR and old != PUBLIC_CIDR
    return {
        "public_exposure": opened_to_internet,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": PUBLIC_CIDR if opened_to_internet else "internal",
        "change_magnitude": "High" if opened_to_internet else "Medium",
    }


def _rule_inbound_custom(old: Any, new: Any) -> Dict[str, Any]:
    """A rule that did not exist before (None) suddenly appears."""
    appeared = old is None and isinstance(new, dict)
    is_public = appeared and new.get("source_cidr") == PUBLIC_CIDR
    return {
        "public_exposure": is_public,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": PUBLIC_CIDR if is_public else ("internal" if appeared else "none"),
        "change_magnitude": "Medium" if appeared else "Low",
    }


def _rule_outbound_destination_cidr(old: Any, new: Any) -> Dict[str, Any]:
    widened = new == PUBLIC_CIDR and old != PUBLIC_CIDR
    return {
        "public_exposure": widened,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": PUBLIC_CIDR if widened else "internal",
        "change_magnitude": "High" if widened else "Medium",
    }


def _rule_internal_port_range(old: Any, new: Any) -> Dict[str, Any]:
    widened = old == "single" and new != "single"
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": "internal",
        "change_magnitude": "Medium" if widened else "Low",
    }


def _rule_peer_sg_reference(old: Any, new: Any) -> Dict[str, Any]:
    added = old is None and new is not None
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": added,
        "port_exposure": "internal",
        "change_magnitude": "Medium" if added else "Low",
    }


def _rule_iam_actions_or_resources(old: Any, new: Any) -> Dict[str, Any]:
    escalated = new == ["*"] or new == "*"
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": escalated,
        "port_exposure": "none",
        "change_magnitude": "High" if escalated else "Medium",
    }


def _rule_trust_principal(old: Any, new: Any) -> Dict[str, Any]:
    # Any change to the trust principal ARN string is treated as adding/
    # changing a trust relationship -- in our schema this always represents
    # an external-account trust being introduced (scenario I2).
    changed = isinstance(old, str) and isinstance(new, str) and old != new
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": changed,
        "port_exposure": "none",
        "change_magnitude": "High" if changed else "Low",
    }


def _rule_requires_mfa(old: Any, new: Any) -> Dict[str, Any]:
    removed = old is True and new is False
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": removed,
        "port_exposure": "none",
        "change_magnitude": "Medium" if removed else "Low",
    }


def _rule_effect(old: Any, new: Any) -> Dict[str, Any]:
    flipped_to_allow = old == "Deny" and new == "Allow"
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": flipped_to_allow,
        "port_exposure": "none",
        "change_magnitude": "High" if flipped_to_allow else "Medium",
    }


def _rule_group_membership(old: Any, new: Any) -> Dict[str, Any]:
    escalated = new == "AdminGroup" and old != "AdminGroup"
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": escalated,
        "port_exposure": "none",
        "change_magnitude": "High" if escalated else "Medium",
    }


def _rule_permissions_boundary(old: Any, new: Any) -> Dict[str, Any]:
    removed = old is not None and new is None
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": removed,
        "port_exposure": "none",
        "change_magnitude": "Medium" if removed else "Low",
    }


def _rule_access_key_count(old: Any, new: Any) -> Dict[str, Any]:
    return {
        "public_exposure": False,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": "none",
        "change_magnitude": "Low",
    }


# attribute_path -> (resource_type, intrinsic_security_sensitivity, rule_fn)
ATTRIBUTE_KNOWLEDGE_BASE: Dict[str, Tuple[str, str, Callable[[Any, Any], Dict[str, Any]]]] = {
    # S3
    "block_public_access": ("s3_bucket", "High", _rule_block_public_access),
    "acl": ("s3_bucket", "High", _rule_acl),
    "encryption.enabled": ("s3_bucket", "High", _rule_encryption_enabled),
    "bucket_policy_principal": ("s3_bucket", "High", _rule_bucket_policy_principal),
    "versioning": ("s3_bucket", "Medium", _rule_low_impact_toggle),
    "logging": ("s3_bucket", "Medium", _rule_low_impact_toggle),
    "lifecycle_rule": ("s3_bucket", "Low", _rule_low_impact_toggle),
    # EC2 Security Group
    "inbound_ssh.source_cidr": ("security_group", "High", _rule_inbound_cidr_generic),
    "inbound_rdp.source_cidr": ("security_group", "High", _rule_inbound_cidr_generic),
    "inbound_custom": ("security_group", "Medium", _rule_inbound_custom),
    "outbound_default.destination_cidr": ("security_group", "Medium", _rule_outbound_destination_cidr),
    "internal_service_port.range": ("security_group", "Medium", _rule_internal_port_range),
    "peer_sg_reference": ("security_group", "Medium", _rule_peer_sg_reference),
    # IAM
    "actions": ("iam_policy", "High", _rule_iam_actions_or_resources),
    "resources": ("iam_policy", "High", _rule_iam_actions_or_resources),
    "trust_principal": ("iam_policy", "High", _rule_trust_principal),
    "requires_mfa": ("iam_policy", "Medium", _rule_requires_mfa),
    "effect": ("iam_policy", "High", _rule_effect),
    "group_membership": ("iam_policy", "High", _rule_group_membership),
    "permissions_boundary": ("iam_policy", "Medium", _rule_permissions_boundary),
    "access_key_count": ("iam_policy", "Low", _rule_access_key_count),
}


def extract_features(
    resource_type_hint: str,
    drift_result: Dict[str, Any],
    drift_frequency: int,
) -> Dict[str, Any]:
    """
    Convert a drift_engine.detect_drift() result into the approved ML feature row.

    Args:
        resource_type_hint: resource type of the record ("s3_bucket",
            "security_group", "iam_policy"). Required because a no-drift
            record has no changed attributes to infer it from.
        drift_result: the dict returned by drift_engine.detect_drift()
        drift_frequency: externally supplied historical drift count for
            this resource (not derivable from a single state comparison)

    Returns:
        A flat dict with exactly the approved feature keys. old_value and
        new_value are never included.
    """
    changes: List[Dict[str, Any]] = drift_result["changes"]

    if len(changes) == 0:
        return {
            "resource_type": resource_type_hint,
            "changed_attribute": "none",
            "security_sensitivity": "Low",
            "public_exposure": False,
            "encryption_change": False,
            "privilege_change": False,
            "port_exposure": "none",
            "change_magnitude": "None",
            "drift_frequency": drift_frequency,
        }

    changed_paths: List[str] = []
    resource_type = resource_type_hint
    security_sensitivity = "Low"
    public_exposure = False
    encryption_change = False
    privilege_change = False
    change_magnitude = "None"
    port_exposure_seen = set()

    for change in changes:
        path = change["attribute"]
        old_val = change["old_value"]
        new_val = change["new_value"]
        changed_paths.append(path)

        kb_entry = ATTRIBUTE_KNOWLEDGE_BASE.get(path)
        if kb_entry is None:
            raise KeyError(
                f"feature_extraction: no knowledge-base rule for attribute "
                f"path '{path}'. Add a rule to ATTRIBUTE_KNOWLEDGE_BASE "
                f"before this attribute can be used in the dataset."
            )

        kb_resource_type, kb_sensitivity, rule_fn = kb_entry
        resource_type = kb_resource_type  # all changes in one record share one resource

        flags = rule_fn(old_val, new_val)

        security_sensitivity = _max_severity(security_sensitivity, kb_sensitivity)
        public_exposure = public_exposure or flags["public_exposure"]
        encryption_change = encryption_change or flags["encryption_change"]
        privilege_change = privilege_change or flags["privilege_change"]
        change_magnitude = _max_severity(change_magnitude, flags["change_magnitude"])
        port_exposure_seen.add(flags["port_exposure"])

    # Combine port_exposure across possibly-multiple changes:
    # public (0.0.0.0/0) > internal > none
    if PUBLIC_CIDR in port_exposure_seen:
        port_exposure = PUBLIC_CIDR
    elif "internal" in port_exposure_seen:
        port_exposure = "internal"
    else:
        port_exposure = "none"

    return {
        "resource_type": resource_type,
        "changed_attribute": "+".join(sorted(changed_paths)),
        "security_sensitivity": security_sensitivity,
        "public_exposure": public_exposure,
        "encryption_change": encryption_change,
        "privilege_change": privilege_change,
        "port_exposure": port_exposure,
        "change_magnitude": change_magnitude,
        "drift_frequency": drift_frequency,
    }


def extract_features_from_states(
    resource_type_hint: str,
    desired: Dict[str, Any],
    actual: Dict[str, Any],
    drift_frequency: int,
) -> Dict[str, Any]:
    """Convenience wrapper: desired/actual states in, feature row out."""
    drift_result = detect_drift(desired, actual)
    return extract_features(resource_type_hint, drift_result, drift_frequency)


if __name__ == "__main__":
    # Small smoke test when run directly.
    desired_example = {
        "bucket_name": "prod-bucket-001",
        "block_public_access": True,
    }
    actual_example = {
        "bucket_name": "prod-bucket-001",
        "block_public_access": False,
    }
    print(extract_features_from_states("s3_bucket", desired_example, actual_example, drift_frequency=2))
