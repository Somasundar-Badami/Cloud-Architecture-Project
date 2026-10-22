"""Tests for the DRAFT expansion pack. Uses moto, so no AWS account is needed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import project_paths  # noqa: F401,E402
import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

import expansion_scenarios as ex  # noqa: E402
from drift_engine import detect_drift  # noqa: E402
from feature_extraction import extract_features  # noqa: E402
from risk_rule_check import rule_based_label  # noqa: E402
from scenario_definitions import SCENARIO_REGISTRY  # noqa: E402
from rds_collector import fetch_rds_instance, normalize_rds_instance  # noqa: E402
import random  # noqa: E402


import copy  # noqa: E402
import pytest  # noqa: E402
import feature_extraction as _fx  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_install():
    """install() mutates global registries; restore them so other test modules still see the original 20."""
    reg, kb = list(SCENARIO_REGISTRY), dict(_fx.ATTRIBUTE_KNOWLEDGE_BASE)
    ex.install()
    yield
    SCENARIO_REGISTRY[:] = reg
    _fx.ATTRIBUTE_KNOWLEDGE_BASE.clear()
    _fx.ATTRIBUTE_KNOWLEDGE_BASE.update(kb)


def test_registry_has_original_20_plus_17_new():
    assert len(SCENARIO_REGISTRY) == 37
    assert [s["scenario_id"] for s in SCENARIO_REGISTRY[:20]][0] == "S1"


def test_install_is_idempotent():
    ex.install()
    assert len(SCENARIO_REGISTRY) == 37


def test_every_new_scenario_drifts_exactly_one_attribute_and_label_matches_rule():
    rng = random.Random(1)
    for s in ex.NEW_SCENARIOS:
        desired = s["baseline_fn"](rng, 1)
        actual = s["mutate_fn"](desired, rng)
        drift = detect_drift(desired, actual)
        assert len(drift["changes"]) == 1, s["scenario_id"]
        feats = extract_features(s["resource_type"], drift, 1)
        assert rule_based_label(feats) == s["risk_label"], s["scenario_id"]


@mock_aws
def test_rds_collector_detects_public_database():
    rds = boto3.client("rds", region_name="us-east-1")
    rds.create_db_instance(DBInstanceIdentifier="orders-db-001", DBInstanceClass="db.t3.micro",
                           Engine="postgres", MasterUsername="u", MasterUserPassword="password123",
                           AllocatedStorage=20, PubliclyAccessible=False, StorageEncrypted=True,
                           BackupRetentionPeriod=7, DeletionProtection=True)
    desired = normalize_rds_instance(fetch_rds_instance(rds, "orders-db-001"))
    rds.modify_db_instance(DBInstanceIdentifier="orders-db-001", PubliclyAccessible=True, ApplyImmediately=True)
    actual = normalize_rds_instance(fetch_rds_instance(rds, "orders-db-001"))
    drift = detect_drift(desired, actual)
    assert [c["attribute"] for c in drift["changes"]] == ["publicly_accessible"]
    assert rule_based_label(extract_features("rds_instance", drift, 0)) == "Critical"
