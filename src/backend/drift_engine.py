"""
drift_engine.py

Generic drift comparison engine.

Compares a "desired state" JSON/dict (what Terraform/IaC declares) against
an "actual state" JSON/dict (what AWS currently reports) and returns the
list of attributes that differ.

Design notes:
- Works on any nested dict structure, not just S3/SG/IAM. This keeps it
  reusable if more resource types are added later.
- Recurses into nested dicts (e.g. desired["encryption"]["enabled"]) so
  a changed sub-field is reported with a dotted path like
  "encryption.enabled" rather than just "encryption".
- Lists and scalars are compared by direct equality (no list-diffing).
  This is a deliberate simplification: our schema avoids putting
  multiple independent rules inside a single list, so list-level
  equality is sufficient and keeps the engine easy to read.
- A key present in one state but missing in the other is treated as a
  drifted attribute, with the missing side reported as None.
"""

from typing import Any, Dict, List


def deep_diff(desired: Dict[str, Any], actual: Dict[str, Any], path: str = "") -> List[Dict[str, Any]]:
    """
    Recursively compare two dicts and return a list of changes.

    Each change is a dict:
        {"attribute": "<dotted.path>", "old_value": <desired value>, "new_value": <actual value>}

    Args:
        desired: the desired-state dict (Terraform/IaC declared config)
        actual: the actual-state dict (live/observed AWS config)
        path: internal recursion helper, do not set manually

    Returns:
        List of change dicts. Empty list means no drift detected.
    """
    changes: List[Dict[str, Any]] = []

    all_keys = set(desired.keys()) | set(actual.keys())

    for key in sorted(all_keys):
        current_path = f"{path}.{key}" if path else key

        desired_val = desired.get(key, None)
        actual_val = actual.get(key, None)

        both_dicts = isinstance(desired_val, dict) and isinstance(actual_val, dict)

        if both_dicts:
            changes.extend(deep_diff(desired_val, actual_val, current_path))
        else:
            if desired_val != actual_val:
                changes.append(
                    {
                        "attribute": current_path,
                        "old_value": desired_val,
                        "new_value": actual_val,
                    }
                )

    return changes


def detect_drift(desired: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    """
    Top-level drift detection entry point.

    Returns:
        {
            "has_drift": bool,
            "num_changes": int,
            "changes": [ {attribute, old_value, new_value}, ... ],
            "changed_attributes": [ "attr1", "attr2", ... ]   # convenience list of paths
        }
    """
    changes = deep_diff(desired, actual)
    return {
        "has_drift": len(changes) > 0,
        "num_changes": len(changes),
        "changes": changes,
        "changed_attributes": [c["attribute"] for c in changes],
    }


if __name__ == "__main__":
    # Tiny smoke test when run directly (not a substitute for tests/test_drift_engine.py)
    desired_example = {
        "resource_type": "aws_s3_bucket",
        "bucket_name": "prod-bucket-001",
        "block_public_access": True,
        "encryption": {"enabled": True, "kms_key_id": "alias/s3-key-001"},
    }
    actual_example = {
        "resource_type": "aws_s3_bucket",
        "bucket_name": "prod-bucket-001",
        "block_public_access": False,
        "encryption": {"enabled": True, "kms_key_id": "alias/s3-key-001"},
    }
    result = detect_drift(desired_example, actual_example)
    print(result)
