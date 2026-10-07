"""
tests/test_feature_extraction.py

Pytest test suite for src/feature_extraction.py.

Covers:
  - Normal cases: one representative scenario per resource type and per
    risk-driving category (public exposure, encryption, privilege,
    operational/low-impact)
  - Edge cases: no drift, multiple simultaneous changes, unknown attribute,
    and a structural guarantee that old_value/new_value never leak into
    the returned feature dict.

Run with:
    pytest tests/test_feature_extraction.py -v
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402
from drift_engine import detect_drift  # noqa: E402
from feature_extraction import (  # noqa: E402
    extract_features,
    extract_features_from_states,
)


# ---------------------------------------------------------------------------
# Normal cases
# ---------------------------------------------------------------------------

def test_s3_public_exposure_scenario_S1():
    """S1: block_public_access True -> False. Should read as public_exposure=True, High."""
    desired = {"bucket_name": "prod-bucket-001", "block_public_access": True}
    actual = {"bucket_name": "prod-bucket-001", "block_public_access": False}
    features = extract_features_from_states("s3_bucket", desired, actual, drift_frequency=1)

    assert features["resource_type"] == "s3_bucket"
    assert features["changed_attribute"] == "block_public_access"
    assert features["public_exposure"] is True
    assert features["privilege_change"] is False
    assert features["encryption_change"] is False
    assert features["security_sensitivity"] == "High"
    assert features["change_magnitude"] == "High"
    assert features["drift_frequency"] == 1


def test_s3_encryption_scenario_S3id():
    """S3id: encryption.enabled True -> False. Should read as encryption_change=True."""
    desired = {
        "bucket_name": "prod-bucket-002",
        "encryption": {"enabled": True, "kms_key_id": "alias/s3-key-002"},
    }
    actual = {
        "bucket_name": "prod-bucket-002",
        "encryption": {"enabled": False, "kms_key_id": "alias/s3-key-002"},
    }
    features = extract_features_from_states("s3_bucket", desired, actual, drift_frequency=3)

    assert features["changed_attribute"] == "encryption.enabled"
    assert features["encryption_change"] is True
    assert features["public_exposure"] is False
    assert features["privilege_change"] is False
    assert features["change_magnitude"] == "Medium"


def test_s3_low_impact_scenario_S6_logging():
    """S6: logging enabled -> disabled. Operational, Low magnitude, no exposure/privilege flags."""
    desired = {"bucket_name": "prod-bucket-003", "logging": "enabled"}
    actual = {"bucket_name": "prod-bucket-003", "logging": "disabled"}
    features = extract_features_from_states("s3_bucket", desired, actual, drift_frequency=6)

    assert features["change_magnitude"] == "Low"
    assert features["public_exposure"] is False
    assert features["encryption_change"] is False
    assert features["privilege_change"] is False
    assert features["security_sensitivity"] == "Medium"


def test_sg_public_exposure_scenario_E1_ssh():
    """E1: SSH inbound source_cidr restricted -> 0.0.0.0/0."""
    desired = {"sg_id": "sg-000001", "inbound_ssh": {"port": 22, "source_cidr": "10.0.0.0/8"}}
    actual = {"sg_id": "sg-000001", "inbound_ssh": {"port": 22, "source_cidr": "0.0.0.0/0"}}
    features = extract_features_from_states("security_group", desired, actual, drift_frequency=2)

    assert features["resource_type"] == "security_group"
    assert features["changed_attribute"] == "inbound_ssh.source_cidr"
    assert features["public_exposure"] is True
    assert features["port_exposure"] == "0.0.0.0/0"
    assert features["change_magnitude"] == "High"


def test_sg_internal_widen_scenario_E6():
    """E6: internal service port widened from a single port to a range (still internal)."""
    desired = {"sg_id": "sg-000002", "internal_service_port": {"port": 5432, "range": "single"}}
    actual = {"sg_id": "sg-000002", "internal_service_port": {"port": 5432, "range": "5000-5999"}}
    features = extract_features_from_states("security_group", desired, actual, drift_frequency=4)

    assert features["public_exposure"] is False
    assert features["port_exposure"] == "internal"
    assert features["change_magnitude"] == "Medium"


def test_iam_privilege_escalation_scenario_I1():
    """I1: IAM policy scoped -> full admin. actions and resources both change at once."""
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
    features = extract_features_from_states("iam_policy", desired, actual, drift_frequency=1)

    assert features["resource_type"] == "iam_policy"
    assert features["changed_attribute"] == "actions+resources"
    assert features["privilege_change"] is True
    assert features["public_exposure"] is False
    assert features["security_sensitivity"] == "High"
    assert features["change_magnitude"] == "High"


def test_iam_deny_to_allow_scenario_I4():
    """I4: explicit Deny flipped to Allow."""
    desired = {"policy_name": "app-policy-004", "effect": "Deny"}
    actual = {"policy_name": "app-policy-004", "effect": "Allow"}
    features = extract_features_from_states("iam_policy", desired, actual, drift_frequency=1)

    assert features["privilege_change"] is True
    assert features["change_magnitude"] == "High"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_edge_case_no_drift_control_scenario_E5():
    """No-drift control case: identical desired/actual states must yield a
    fully 'inactive' feature row, not a false positive."""
    desired = {"sg_id": "sg-000005", "inbound_https": {"port": 443, "source_cidr": "0.0.0.0/0"}}
    actual = {"sg_id": "sg-000005", "inbound_https": {"port": 443, "source_cidr": "0.0.0.0/0"}}
    features = extract_features_from_states("security_group", desired, actual, drift_frequency=5)

    assert features["changed_attribute"] == "none"
    assert features["public_exposure"] is False
    assert features["encryption_change"] is False
    assert features["privilege_change"] is False
    assert features["port_exposure"] == "none"
    assert features["change_magnitude"] == "None"
    # drift_frequency is still passed through even with no drift
    assert features["drift_frequency"] == 5


def test_edge_case_multiple_simultaneous_changes_take_max_severity():
    """When two changed attributes disagree on severity, the record-level
    feature should take the MORE severe value, not the first or last one."""
    desired = {
        "bucket_name": "prod-bucket-007",
        "logging": "enabled",              # Low magnitude if changed
        "block_public_access": True,       # High magnitude if changed
    }
    actual = {
        "bucket_name": "prod-bucket-007",
        "logging": "disabled",             # changed -> Low
        "block_public_access": False,      # changed -> High
    }
    features = extract_features_from_states("s3_bucket", desired, actual, drift_frequency=1)

    assert features["changed_attribute"] == "block_public_access+logging"
    assert features["change_magnitude"] == "High"  # max(Low, High) == High
    assert features["public_exposure"] is True


def test_edge_case_unknown_attribute_raises_keyerror():
    """An attribute path not present in ATTRIBUTE_KNOWLEDGE_BASE must fail
    loudly rather than silently guessing a feature value."""
    desired = {"some_new_field": "old_value_here"}
    actual = {"some_new_field": "new_value_here"}
    drift_result = detect_drift(desired, actual)

    with pytest.raises(KeyError):
        extract_features("s3_bucket", drift_result, drift_frequency=0)


def test_edge_case_old_and_new_value_never_appear_in_output():
    """Structural guarantee: no matter the input, the returned feature dict
    must never contain raw old_value/new_value keys or values."""
    desired = {"trust_principal": "arn:aws:iam::111111111111:root"}
    actual = {"trust_principal": "arn:aws:iam::999999999999:root"}
    features = extract_features_from_states("iam_policy", desired, actual, drift_frequency=0)

    assert "old_value" not in features
    assert "new_value" not in features
    # Also confirm the raw ARNs themselves don't leak into any feature value
    for value in features.values():
        assert value != "arn:aws:iam::111111111111:root"
        assert value != "arn:aws:iam::999999999999:root"


def test_edge_case_drift_frequency_passthrough_is_exact():
    """drift_frequency is caller-supplied and must be passed through unchanged."""
    desired = {"acl": "private"}
    actual = {"acl": "public-read"}
    for freq in [0, 1, 7, 15]:
        features = extract_features_from_states("s3_bucket", desired, actual, drift_frequency=freq)
        assert features["drift_frequency"] == freq


def test_edge_case_feature_dict_has_exactly_the_approved_keys():
    """The output schema must match the approved feature list exactly --
    no extra keys, no missing keys."""
    desired = {"acl": "private"}
    actual = {"acl": "public-read"}
    features = extract_features_from_states("s3_bucket", desired, actual, drift_frequency=0)

    expected_keys = {
        "resource_type",
        "changed_attribute",
        "security_sensitivity",
        "public_exposure",
        "encryption_change",
        "privilege_change",
        "port_exposure",
        "change_magnitude",
        "drift_frequency",
    }
    assert set(features.keys()) == expected_keys
