"""
tests/test_drift_engine.py

Pytest test suite for src/drift_engine.py.

Each test uses explicit, hand-written desired/actual dicts (independent of
the dataset generator) so drift_engine's correctness is verified on its own,
not by circular reference to the generator that will later use it.

Run with:
    pytest tests/test_drift_engine.py -v
"""

import sys
import os

# Allow running pytest from the project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from drift_engine import detect_drift  # noqa: E402


def test_no_drift_identical_dicts():
    """Identical desired and actual states -> no drift at all."""
    desired = {
        "resource_type": "aws_s3_bucket",
        "bucket_name": "prod-bucket-001",
        "block_public_access": True,
    }
    actual = {
        "resource_type": "aws_s3_bucket",
        "bucket_name": "prod-bucket-001",
        "block_public_access": True,
    }
    result = detect_drift(desired, actual)
    assert result["has_drift"] is False
    assert result["num_changes"] == 0
    assert result["changes"] == []
    assert result["changed_attributes"] == []


def test_single_scalar_change():
    """Exactly one top-level scalar field differs."""
    desired = {"bucket_name": "prod-bucket-001", "acl": "private"}
    actual = {"bucket_name": "prod-bucket-001", "acl": "public-read"}
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["num_changes"] == 1
    assert result["changed_attributes"] == ["acl"]
    change = result["changes"][0]
    assert change["old_value"] == "private"
    assert change["new_value"] == "public-read"


def test_multiple_scalar_changes():
    """Several independent top-level fields differ at once."""
    desired = {
        "bucket_name": "prod-bucket-001",
        "versioning": "enabled",
        "logging": "enabled",
        "acl": "private",
    }
    actual = {
        "bucket_name": "prod-bucket-001",
        "versioning": "disabled",
        "logging": "disabled",
        "acl": "private",
    }
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["num_changes"] == 2
    assert set(result["changed_attributes"]) == {"versioning", "logging"}


def test_nested_dict_change_reports_dotted_path():
    """A change inside a nested dict should be reported as 'parent.child'."""
    desired = {
        "bucket_name": "prod-bucket-001",
        "encryption": {"enabled": True, "kms_key_id": "alias/s3-key-001"},
    }
    actual = {
        "bucket_name": "prod-bucket-001",
        "encryption": {"enabled": False, "kms_key_id": "alias/s3-key-001"},
    }
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["num_changes"] == 1
    assert result["changed_attributes"] == ["encryption.enabled"]
    change = result["changes"][0]
    assert change["old_value"] is True
    assert change["new_value"] is False


def test_missing_key_in_actual_state():
    """A key present in desired but absent in actual (e.g. rule deleted)."""
    desired = {
        "bucket_name": "prod-bucket-001",
        "lifecycle_rule": {"enabled": True, "retention_days": 365},
    }
    actual = {
        "bucket_name": "prod-bucket-001",
        # lifecycle_rule entirely absent -> treated as None on the actual side
    }
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    # desired side is a dict, actual side is missing (None) -> NOT both dicts,
    # so this is reported as ONE change at "lifecycle_rule", not recursed into.
    assert result["changed_attributes"] == ["lifecycle_rule"]
    change = result["changes"][0]
    assert change["old_value"] == {"enabled": True, "retention_days": 365}
    assert change["new_value"] is None


def test_key_added_in_actual_state():
    """A key absent in desired but present in actual (e.g. unexpected new rule)."""
    desired = {
        "sg_id": "sg-000001",
        "inbound_custom": None,
    }
    actual = {
        "sg_id": "sg-000001",
        "inbound_custom": {"port": 8080, "source_cidr": "0.0.0.0/0"},
    }
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["changed_attributes"] == ["inbound_custom"]
    change = result["changes"][0]
    assert change["old_value"] is None
    assert change["new_value"] == {"port": 8080, "source_cidr": "0.0.0.0/0"}


def test_list_value_change():
    """List-valued fields are compared by direct equality (no list-diffing)."""
    desired = {
        "policy_name": "app-policy-001",
        "actions": ["s3:GetObject"],
        "resources": ["arn:aws:s3:::prod-data-001/*"],
    }
    actual = {
        "policy_name": "app-policy-001",
        "actions": ["*"],
        "resources": ["*"],
    }
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["num_changes"] == 2
    assert set(result["changed_attributes"]) == {"actions", "resources"}


def test_list_value_unchanged_no_false_positive():
    """Identical lists must NOT be reported as drift."""
    desired = {"actions": ["s3:GetObject", "s3:PutObject"]}
    actual = {"actions": ["s3:GetObject", "s3:PutObject"]}
    result = detect_drift(desired, actual)
    assert result["has_drift"] is False
    assert result["changes"] == []


def test_boolean_true_to_false_change():
    """Explicit boolean flip, the most common drift pattern in this project."""
    desired = {"requires_mfa": True}
    actual = {"requires_mfa": False}
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["num_changes"] == 1
    change = result["changes"][0]
    assert change["attribute"] == "requires_mfa"
    assert change["old_value"] is True
    assert change["new_value"] is False


def test_boolean_false_to_true_is_also_detected():
    """Sanity check: direction of the flip doesn't matter, both are drift."""
    desired = {"requires_mfa": False}
    actual = {"requires_mfa": True}
    result = detect_drift(desired, actual)
    assert result["has_drift"] is True
    assert result["changed_attributes"] == ["requires_mfa"]


def test_multiple_nested_and_top_level_changes_together():
    """Realistic mixed case: one nested change + one top-level change at once."""
    desired = {
        "bucket_name": "prod-bucket-007",
        "acl": "private",
        "encryption": {"enabled": True, "kms_key_id": "alias/s3-key-007"},
    }
    actual = {
        "bucket_name": "prod-bucket-007",
        "acl": "public-read",
        "encryption": {"enabled": False, "kms_key_id": "alias/s3-key-007"},
    }
    result = detect_drift(desired, actual)
    assert result["num_changes"] == 2
    assert set(result["changed_attributes"]) == {"acl", "encryption.enabled"}
