"""
tests/test_dataset_generator.py

Pytest tests for src/dataset_generator.py, src/scenario_definitions.py, and
validate_dataset.py's check functions.

These re-run the real generator (not a mock) so every assertion here is
checked against actual generated output, using the actual drift_engine and
feature_extraction modules.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dataset_generator import generate_records, GLOBAL_SEED  # noqa: E402
from scenario_definitions import SCENARIO_REGISTRY, ALLOWED_RISK_LABELS  # noqa: E402
from drift_engine import detect_drift  # noqa: E402
from risk_rule_check import rule_based_label  # noqa: E402
import validate_dataset  # noqa: E402


# Generate once and reuse across tests in this module (deterministic, fast).
_RECORDS = generate_records()


def test_scenario_registry_has_exactly_20_scenarios():
    assert len(SCENARIO_REGISTRY) == 20


def test_scenario_registry_breakdown_matches_approved_counts():
    s3_count = sum(1 for s in SCENARIO_REGISTRY if s["resource_type"] == "s3_bucket")
    sg_count = sum(1 for s in SCENARIO_REGISTRY if s["resource_type"] == "security_group")
    iam_count = sum(1 for s in SCENARIO_REGISTRY if s["resource_type"] == "iam_policy")
    assert s3_count == 7
    assert sg_count == 7
    assert iam_count == 6


def test_total_record_count_within_target_range():
    assert 600 <= len(_RECORDS) <= 900


def test_generation_is_deterministic_given_fixed_seed():
    """Re-running the generator with the same GLOBAL_SEED must produce
    byte-identical record_id -> risk_label and record_id -> features
    mappings."""
    records_run_2 = generate_records()
    assert len(_RECORDS) == len(records_run_2)
    for r1, r2 in zip(_RECORDS, records_run_2):
        assert r1["record_id"] == r2["record_id"]
        assert r1["desired_state"] == r2["desired_state"]
        assert r1["actual_state"] == r2["actual_state"]
        assert r1["features"] == r2["features"]
        assert r1["risk_label"] == r2["risk_label"]


def test_every_record_has_required_fields():
    required_fields = {
        "record_id", "scenario_id", "group_id", "resource_type",
        "desired_state", "actual_state", "drift_result", "features", "risk_label",
    }
    for r in _RECORDS:
        assert required_fields.issubset(r.keys())


def test_all_20_scenarios_are_represented():
    scenario_ids_present = {r["scenario_id"] for r in _RECORDS}
    scenario_ids_expected = {s["scenario_id"] for s in SCENARIO_REGISTRY}
    assert scenario_ids_present == scenario_ids_expected


def test_all_four_risk_labels_present_and_valid():
    labels_present = {r["risk_label"] for r in _RECORDS}
    assert labels_present == ALLOWED_RISK_LABELS


def test_non_drift_control_case_E5_has_zero_drift():
    e5_records = [r for r in _RECORDS if r["scenario_id"] == "E5"]
    assert len(e5_records) > 0
    for r in e5_records:
        assert r["drift_result"]["has_drift"] is False
        assert r["drift_result"]["num_changes"] == 0
        assert r["features"]["changed_attribute"] == "none"
        assert r["risk_label"] == "Low"
        # desired and actual must be genuinely identical for the control case
        assert r["desired_state"] == r["actual_state"]


def test_every_record_drift_result_matches_independent_recomputation():
    """No hand-fabricated drift results: recompute detect_drift() from the
    stored states and confirm it matches what was stored."""
    for r in _RECORDS:
        recomputed = detect_drift(r["desired_state"], r["actual_state"])
        assert recomputed == r["drift_result"], f"Mismatch for {r['record_id']}"


def test_features_never_contain_raw_old_or_new_value_keys():
    for r in _RECORDS:
        assert "old_value" not in r["features"]
        assert "new_value" not in r["features"]


def test_drifted_records_have_nonempty_changed_attribute():
    for r in _RECORDS:
        if r["drift_result"]["has_drift"]:
            assert r["features"]["changed_attribute"] != "none"
        else:
            assert r["features"]["changed_attribute"] == "none"


def test_scenario_id_S1_records_are_all_public_exposure_and_critical():
    s1_records = [r for r in _RECORDS if r["scenario_id"] == "S1"]
    assert len(s1_records) > 0
    for r in s1_records:
        assert r["features"]["public_exposure"] is True
        assert r["risk_label"] == "Critical"
        assert r["features"]["changed_attribute"] == "block_public_access"


def test_iam_privilege_escalation_scenario_I1_records_are_critical():
    i1_records = [r for r in _RECORDS if r["scenario_id"] == "I1"]
    assert len(i1_records) > 0
    for r in i1_records:
        assert r["features"]["privilege_change"] is True
        assert r["risk_label"] == "Critical"
        assert r["actual_state"]["actions"] == ["*"]
        assert r["actual_state"]["resources"] == ["*"]


def test_group_id_groups_variations_of_the_same_entity_consistently():
    """All records sharing a group_id must share scenario_id and
    resource_type (they represent the same underlying entity, only
    secondary parameters differ across variations)."""
    by_group = {}
    for r in _RECORDS:
        by_group.setdefault(r["group_id"], []).append(r)

    for group_id, group_records in by_group.items():
        scenario_ids = {r["scenario_id"] for r in group_records}
        resource_types = {r["resource_type"] for r in group_records}
        assert len(scenario_ids) == 1, f"group_id {group_id} spans multiple scenarios"
        assert len(resource_types) == 1, f"group_id {group_id} spans multiple resource types"


def test_variations_within_an_entity_are_not_all_identical():
    """Meaningful variation check: within at least one multi-variation
    group, the desired_state JSON must differ across variations (secondary
    parameters like retention_days/bucket prefix/CIDR choice should vary)."""
    by_group = {}
    for r in _RECORDS:
        by_group.setdefault(r["group_id"], []).append(r)

    found_variation = False
    for group_id, group_records in by_group.items():
        if len(group_records) < 2:
            continue
        desired_states = [r["desired_state"] for r in group_records]
        if len(set(str(d) for d in desired_states)) > 1:
            found_variation = True
            break
    assert found_variation, "Expected at least one group with varying desired_state across variations"


# ---------------------------------------------------------------------------
# Validation-report function tests
# ---------------------------------------------------------------------------

def test_validation_report_runs_and_passes_overall():
    report = validate_dataset.run_all_checks()
    assert report["overall_passed"] is True


def test_validation_report_no_missing_values():
    report = validate_dataset.run_all_checks()
    assert report["missing_values"]["total_missing_values"] == 0


def test_validation_report_no_full_row_duplicates():
    report = validate_dataset.run_all_checks()
    assert report["duplicates"]["full_row_duplicates"] == 0


def test_validation_report_state_drift_consistency_zero_mismatches():
    report = validate_dataset.run_all_checks()
    assert report["state_drift_consistency"]["mismatches_found"] == 0


def test_validation_report_risk_label_rule_check_only_flags_E7():
    """Documents the one known, explained rule/label mismatch (scenario E7).
    If this test starts failing because OTHER scenarios also mismatch, that
    is a real regression worth investigating -- not something to silence."""
    report = validate_dataset.run_all_checks()
    mismatches = report["risk_label_rule_check"]["mismatches_by_scenario"]
    assert set(mismatches.keys()) == {"E7"}


def test_rule_based_label_matches_approved_label_for_19_of_20_scenarios():
    mismatch_scenarios = []
    for scenario in SCENARIO_REGISTRY:
        matching_records = [r for r in _RECORDS if r["scenario_id"] == scenario["scenario_id"]]
        sample = matching_records[0]
        predicted = rule_based_label(sample["features"])
        if predicted != scenario["risk_label"]:
            mismatch_scenarios.append(scenario["scenario_id"])
    assert mismatch_scenarios == ["E7"]
