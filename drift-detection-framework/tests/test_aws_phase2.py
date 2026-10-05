"""
tests/test_aws_phase2.py

Phase 2 (EC2 Security Group + IAM role) of the AWS integration layer.
All tests use hand-written boto3-shaped responses or botocore Stubber --
no AWS credentials or network access needed.

The central check: a change made to a REAL AWS resource (expressed as the
raw API response AWS would return after that change) must normalize to the
same changed attribute and the same ML features as the corresponding
approved synthetic scenario's mutate function, so the trained model sees
the same input it was trained on.

Run with:
    pytest tests/test_aws_phase2.py -v
"""

import copy
import json
import os
import random
import sys
import urllib.parse

import boto3
import pytest
from botocore.stub import Stubber

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aws_normalizer import (  # noqa: E402
    ADMIN_POLICY_ARN,
    normalize_iam_role_actual_state,
    normalize_sg_actual_state,
)
from aws_state import (  # noqa: E402
    AWSConfigurationError,
    CATEGORY_ACCESS_DENIED,
    CATEGORY_NOT_FOUND,
    fetch_iam_role_raw_config,
    fetch_security_group_raw_config,
)
from drift_engine import detect_drift  # noqa: E402
from feature_extraction import extract_features  # noqa: E402
from portable_model import PortableRiskModel  # noqa: E402
from scenario_definitions import SCENARIO_REGISTRY  # noqa: E402

PORTABLE_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "portable_model.json")
SCENARIOS = {s["scenario_id"]: s for s in SCENARIO_REGISTRY}

SG_ID = "sg-0123456789abcdef0"
SG_NAME = "drift-demo-sandbox-web"
ACCOUNT = "111122223333"
OTHER_ACCOUNT = "444455556666"
ROLE = "drift-demo-sandbox-app-role"
POLICY = "drift-demo-sandbox-app-access"
BOUNDARY = f"arn:aws:iam::{ACCOUNT}:policy/drift-demo-sandbox-boundary"
BUCKET_ARN = "arn:aws:s3:::drift-demo-sandbox-abcd1234/*"


# ---------------------------------------------------------------------------
# Desired states -- must equal what terraform/desired_state.tf writes
# ---------------------------------------------------------------------------

SG_DESIRED = {
    "resource_type": "aws_security_group",
    "sg_id": SG_ID,
    "instance_name": SG_NAME,
    "inbound_ssh": {"port": 22, "source_cidr": "10.0.0.0/8"},
    "inbound_rdp": {"port": 3389, "source_cidr": "10.0.0.0/8"},
    "inbound_https": {"port": 443, "source_cidr": "0.0.0.0/0"},
    "inbound_custom": None,
    "outbound_default": {"port": "all", "destination_cidr": "10.0.0.0/8"},
    "internal_service_port": {"port": 5432, "range": "single"},
    "peer_sg_reference": None,
}

IAM_DESIRED = {
    "resource_type": "aws_iam_entity",
    "entity_name": ROLE,
    "actions": ["s3:GetObject"],
    "resources": [BUCKET_ARN],
    "effect": "Allow",
    "requires_mfa": True,
    "trust_principal": f"arn:aws:iam::{ACCOUNT}:root",
    "permissions_boundary": BOUNDARY,
    "group_membership": "StandardAccess",
}


def _rule(port, cidr, to_port=None):
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": to_port or port,
            "IpRanges": [{"CidrIp": cidr}], "Ipv6Ranges": [], "UserIdGroupPairs": []}


def sg_response():
    """What describe_security_groups returns for the Terraform-declared group."""
    return {
        "GroupId": SG_ID,
        "GroupName": SG_NAME,
        "IpPermissions": [
            _rule(22, "10.0.0.0/8"),
            _rule(3389, "10.0.0.0/8"),
            _rule(443, "0.0.0.0/0"),
            _rule(5432, "10.0.0.0/8"),
        ],
        "IpPermissionsEgress": [
            {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "10.0.0.0/8"}], "Ipv6Ranges": [], "UserIdGroupPairs": []},
        ],
    }


def iam_raw():
    return {
        "role": {
            "RoleName": ROLE,
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"},
                               "Action": "sts:AssumeRole"}],
            },
            "PermissionsBoundary": {"PermissionsBoundaryType": "Policy", "PermissionsBoundaryArn": BOUNDARY},
        },
        "inline_policy": {
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "PrimaryAccess", "Effect": "Allow", "Action": ["s3:GetObject"], "Resource": [BUCKET_ARN],
                "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}},
            }],
        },
        "attached_policy_arns": [],
    }


def normalize_sg(resp):
    return normalize_sg_actual_state(resp, SG_NAME, 5432)


# ---------------------------------------------------------------------------
# Real-world changes, expressed as the AWS response after the change
# ---------------------------------------------------------------------------

def sg_after(scenario_id):
    r = sg_response()
    perms = r["IpPermissions"]
    if scenario_id == "E1":
        perms.append(_rule(22, "0.0.0.0/0"))            # authorize-security-group-ingress --port 22 --cidr 0.0.0.0/0
    elif scenario_id == "E2":
        perms[1] = _rule(3389, "0.0.0.0/0")
    elif scenario_id == "E3":
        perms.append(_rule(8080, "0.0.0.0/0"))
    elif scenario_id == "E4":
        r["IpPermissionsEgress"][0]["IpRanges"] = [{"CidrIp": "0.0.0.0/0"}]
    elif scenario_id == "E5":
        pass
    elif scenario_id == "E6":
        perms.append(_rule(5000, "10.0.0.0/8", to_port=5999))
    elif scenario_id == "E7":
        perms[3]["UserIdGroupPairs"] = [{"GroupId": "sg-0fedcba9876543210", "UserId": ACCOUNT}]
    return r


def iam_after(scenario_id):
    raw = iam_raw()
    stmt = raw["inline_policy"]["Statement"][0]
    if scenario_id == "I1":
        stmt["Action"], stmt["Resource"] = "*", "*"
    elif scenario_id == "I2":
        raw["role"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"]["AWS"] = f"arn:aws:iam::{OTHER_ACCOUNT}:root"
    elif scenario_id == "I3":
        del stmt["Condition"]
    elif scenario_id == "I5":
        raw["attached_policy_arns"] = [ADMIN_POLICY_ARN]
    elif scenario_id == "I6":
        del raw["role"]["PermissionsBoundary"]
    return raw


# ---------------------------------------------------------------------------
# Normalization of the undrifted resources
# ---------------------------------------------------------------------------

def test_sg_matching_config_has_no_drift():
    assert normalize_sg(sg_response()) == SG_DESIRED
    assert detect_drift(SG_DESIRED, normalize_sg(sg_response()))["has_drift"] is False


def test_iam_matching_config_has_no_drift():
    assert normalize_iam_role_actual_state(iam_raw()) == IAM_DESIRED


def test_sg_desired_state_shape_matches_synthetic_baseline():
    synthetic = SCENARIOS["E5"]["baseline_fn"](random.Random(0), 1)
    assert set(SG_DESIRED) == set(synthetic)


def test_iam_desired_state_shape_matches_synthetic_baseline():
    synthetic = SCENARIOS["I1"]["baseline_fn"](random.Random(0), 1)
    assert set(IAM_DESIRED) == set(synthetic)


# ---------------------------------------------------------------------------
# Real change -> same attribute/features as the approved scenario
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario_id", ["E1", "E2", "E3", "E4", "E5", "E6", "E7"])
def test_sg_real_change_matches_synthetic_scenario(scenario_id):
    real_drift = detect_drift(SG_DESIRED, normalize_sg(sg_after(scenario_id)))
    synthetic_actual = SCENARIOS[scenario_id]["mutate_fn"](copy.deepcopy(SG_DESIRED), random.Random(0))
    synthetic_drift = detect_drift(SG_DESIRED, synthetic_actual)

    assert real_drift["changed_attributes"] == synthetic_drift["changed_attributes"]
    assert extract_features("security_group", real_drift, 0) == extract_features("security_group", synthetic_drift, 0)


@pytest.mark.parametrize("scenario_id", ["I1", "I2", "I3", "I5", "I6"])
def test_iam_real_change_matches_synthetic_scenario(scenario_id):
    real_drift = detect_drift(IAM_DESIRED, normalize_iam_role_actual_state(iam_after(scenario_id)))
    synthetic_actual = SCENARIOS[scenario_id]["mutate_fn"](copy.deepcopy(IAM_DESIRED), random.Random(0))
    synthetic_drift = detect_drift(IAM_DESIRED, synthetic_actual)

    assert real_drift["changed_attributes"] == synthetic_drift["changed_attributes"]
    assert extract_features("iam_policy", real_drift, 0) == extract_features("iam_policy", synthetic_drift, 0)


@pytest.mark.parametrize("scenario_id", ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "I1", "I2", "I3", "I5", "I6"])
def test_primary_model_labels_real_changes_like_the_scenario(scenario_id):
    """Empirical check of the deployed (portable) model on real-shaped input.
    Holds because these feature rows match training rows; see README for why
    this is not evidence of generalization to unseen kinds of drift."""
    model = PortableRiskModel.load(PORTABLE_PATH)
    if scenario_id.startswith("E"):
        drift = detect_drift(SG_DESIRED, normalize_sg(sg_after(scenario_id)))
        features = extract_features("security_group", drift, 0)
    else:
        drift = detect_drift(IAM_DESIRED, normalize_iam_role_actual_state(iam_after(scenario_id)))
        features = extract_features("iam_policy", drift, 0)
    assert model.explain(features)["predicted_label"] == SCENARIOS[scenario_id]["risk_label"]


# ---------------------------------------------------------------------------
# SG normalization edge cases
# ---------------------------------------------------------------------------

def test_sg_ipv6_any_counts_as_public():
    r = sg_response()
    r["IpPermissions"].append({"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [],
                               "Ipv6Ranges": [{"CidrIpv6": "::/0"}], "UserIdGroupPairs": []})
    assert normalize_sg(r)["inbound_ssh"]["source_cidr"] == "0.0.0.0/0"


def test_sg_all_traffic_public_rule_exposes_every_named_port():
    r = sg_response()
    r["IpPermissions"].append({"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                               "Ipv6Ranges": [], "UserIdGroupPairs": []})
    state = normalize_sg(r)
    assert state["inbound_ssh"]["source_cidr"] == "0.0.0.0/0"
    assert state["inbound_rdp"]["source_cidr"] == "0.0.0.0/0"
    assert state["inbound_custom"] == {"port": "all", "source_cidr": "0.0.0.0/0"}


def test_sg_removed_ssh_rule_becomes_none():
    r = sg_response()
    del r["IpPermissions"][0]
    assert normalize_sg(r)["inbound_ssh"] is None


def test_sg_internal_range_replacing_single_port():
    r = sg_response()
    r["IpPermissions"][3] = _rule(5000, "10.0.0.0/8", to_port=5999)
    state = normalize_sg(r)
    assert state["internal_service_port"] == {"port": 5432, "range": "5000-5999"}
    assert state["inbound_custom"] is None


def test_sg_no_egress_rules():
    r = sg_response()
    r["IpPermissionsEgress"] = []
    assert normalize_sg(r)["outbound_default"] is None


# ---------------------------------------------------------------------------
# IAM normalization edge cases
# ---------------------------------------------------------------------------

def test_iam_deleted_inline_policy():
    raw = iam_raw()
    raw["inline_policy"] = None
    state = normalize_iam_role_actual_state(raw)
    assert state["actions"] == [] and state["effect"] is None and state["requires_mfa"] is False


def test_iam_string_action_and_single_statement_dict():
    raw = iam_raw()
    stmt = raw["inline_policy"]["Statement"][0]
    stmt["Action"] = "s3:GetObject"
    raw["inline_policy"]["Statement"] = stmt
    assert normalize_iam_role_actual_state(raw)["actions"] == ["s3:GetObject"]


def test_iam_primary_statement_selected_by_sid():
    raw = iam_raw()
    raw["inline_policy"]["Statement"].insert(0, {"Sid": "Other", "Effect": "Deny", "Action": "s3:DeleteBucket",
                                                 "Resource": "*"})
    assert normalize_iam_role_actual_state(raw)["effect"] == "Allow"


def test_iam_service_trust_principal():
    raw = iam_raw()
    raw["role"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"] = {"Service": "lambda.amazonaws.com"}
    assert normalize_iam_role_actual_state(raw)["trust_principal"] == "service:lambda.amazonaws.com"


def test_iam_effect_flip_to_allow_is_privilege_change():
    desired = dict(IAM_DESIRED, effect="Deny")
    raw = iam_raw()
    drift = detect_drift(desired, normalize_iam_role_actual_state(raw))
    assert drift["changed_attributes"] == ["effect"]
    assert extract_features("iam_policy", drift, 0)["privilege_change"] is True


# ---------------------------------------------------------------------------
# Collectors (botocore Stubber -- real boto3 code paths, no network)
# ---------------------------------------------------------------------------

def _client(service):
    return boto3.client(service, region_name="us-east-1", aws_access_key_id="testing",
                        aws_secret_access_key="testing")


def test_fetch_security_group_success():
    ec2 = _client("ec2")
    with Stubber(ec2) as stub:
        stub.add_response("describe_security_groups", {"SecurityGroups": [sg_response()]}, {"GroupIds": [SG_ID]})
        assert fetch_security_group_raw_config(ec2, SG_ID)["GroupId"] == SG_ID


def test_fetch_security_group_not_found():
    ec2 = _client("ec2")
    with Stubber(ec2) as stub:
        stub.add_client_error("describe_security_groups", service_error_code="InvalidGroup.NotFound")
        with pytest.raises(AWSConfigurationError) as exc:
            fetch_security_group_raw_config(ec2, SG_ID)
    assert exc.value.category == CATEGORY_NOT_FOUND


def test_fetch_security_group_access_denied():
    ec2 = _client("ec2")
    with Stubber(ec2) as stub:
        stub.add_client_error("describe_security_groups", service_error_code="UnauthorizedOperation")
        with pytest.raises(AWSConfigurationError) as exc:
            fetch_security_group_raw_config(ec2, SG_ID)
    assert exc.value.category == CATEGORY_ACCESS_DENIED


def _wire(document):
    """IAM returns policy documents URL-encoded on the wire."""
    return urllib.parse.quote(json.dumps(document))


def _stub_iam(stub, policy_missing=False):
    role = dict(iam_raw()["role"], Path="/", RoleId="AROAEXAMPLEID123456", Arn=f"arn:aws:iam::{ACCOUNT}:role/{ROLE}",
                CreateDate="2026-01-01T00:00:00Z")
    role["AssumeRolePolicyDocument"] = _wire(role["AssumeRolePolicyDocument"])
    stub.add_response("get_role", {"Role": role}, {"RoleName": ROLE})
    if policy_missing:
        stub.add_client_error("get_role_policy", service_error_code="NoSuchEntity")
    else:
        stub.add_response("get_role_policy", {"RoleName": ROLE, "PolicyName": POLICY,
                                              "PolicyDocument": _wire(iam_raw()["inline_policy"])},
                          {"RoleName": ROLE, "PolicyName": POLICY})
    stub.add_response("list_attached_role_policies",
                      {"AttachedPolicies": [{"PolicyName": "AdministratorAccess", "PolicyArn": ADMIN_POLICY_ARN}],
                       "IsTruncated": False},
                      {"RoleName": ROLE})


def test_fetch_iam_role_success_and_normalizes():
    iam = _client("iam")
    with Stubber(iam) as stub:
        _stub_iam(stub)
        raw = fetch_iam_role_raw_config(iam, ROLE, POLICY)
    state = normalize_iam_role_actual_state(raw)
    assert raw["attached_policy_arns"] == [ADMIN_POLICY_ARN]
    assert raw["inline_policy"] == iam_raw()["inline_policy"]
    assert state == dict(IAM_DESIRED, group_membership="AdminGroup")


def test_fetch_iam_role_missing_inline_policy_is_not_an_error():
    iam = _client("iam")
    with Stubber(iam) as stub:
        _stub_iam(stub, policy_missing=True)
        raw = fetch_iam_role_raw_config(iam, ROLE, POLICY)
    assert raw["inline_policy"] is None


def test_fetch_iam_role_not_found():
    iam = _client("iam")
    with Stubber(iam) as stub:
        stub.add_client_error("get_role", service_error_code="NoSuchEntity")
        with pytest.raises(AWSConfigurationError) as exc:
            fetch_iam_role_raw_config(iam, ROLE, POLICY)
    assert exc.value.category == CATEGORY_NOT_FOUND
