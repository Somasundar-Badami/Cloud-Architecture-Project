"""
tests/test_ml_evaluation_audit.py

Pytest tests for src/ml_evaluation_audit.py.

These re-run the real audit functions against the real dataset (no mocks),
so passing tests confirm the audit's own claims are reproducible and
internally consistent -- not just that the code executes.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from ml_evaluation_audit import (  # noqa: E402
    get_scenario_group_split,
    report_scenario_groups,
    report_class_distribution,
    report_resource_type_risk_label_combos,
    report_unseen_combo_model_impact,
    report_e7_vs_i3_i6_feature_sufficiency,
    report_changed_attribute_encoding_check,
    methodological_limitations_report,
    run_audit,
)


# Computed once and reused -- expensive-ish (retrains a couple of models),
# but deterministic given the fixed seed.
_SPLIT_DATA = get_scenario_group_split()


# ---------------------------------------------------------------------------
# 1-2. Scenario group split reporting
# ---------------------------------------------------------------------------

def test_scenario_group_report_has_no_overlap_between_train_and_test():
    report = report_scenario_groups(_SPLIT_DATA)
    train_set = set(report["train_scenario_ids"])
    test_set = set(report["test_scenario_ids"])
    assert train_set.isdisjoint(test_set)
    assert report["leakage_check"]["num_scenarios_leaked"] == 0


def test_scenario_group_report_covers_all_20_scenarios():
    report = report_scenario_groups(_SPLIT_DATA)
    all_scenarios = set(report["train_scenario_ids"]) | set(report["test_scenario_ids"])
    assert len(all_scenarios) == 20


def test_scenario_group_split_is_reproducible():
    """Re-running the split with the same seed must give identical groups."""
    split_data_2 = get_scenario_group_split()
    report_1 = report_scenario_groups(_SPLIT_DATA)
    report_2 = report_scenario_groups(split_data_2)
    assert report_1["train_scenario_ids"] == report_2["train_scenario_ids"]
    assert report_1["test_scenario_ids"] == report_2["test_scenario_ids"]


# ---------------------------------------------------------------------------
# 3. Class distribution
# ---------------------------------------------------------------------------

def test_class_distribution_totals_match_split_sizes():
    report = report_class_distribution(_SPLIT_DATA)
    assert report["train_total"] == len(_SPLIT_DATA["train_idx"])
    assert report["test_total"] == len(_SPLIT_DATA["test_idx"])


def test_class_distribution_covers_all_four_risk_levels_as_keys():
    report = report_class_distribution(_SPLIT_DATA)
    expected = {"Low", "Medium", "High", "Critical"}
    assert set(report["train_class_distribution"].keys()) == expected
    assert set(report["test_class_distribution"].keys()) == expected


def test_class_distribution_flags_classes_absent_from_test_correctly():
    report = report_class_distribution(_SPLIT_DATA)
    for label in report["classes_absent_from_test"]:
        assert report["test_class_distribution"][label] == 0


# ---------------------------------------------------------------------------
# 4. resource_type x risk_label combination analysis
# ---------------------------------------------------------------------------

def test_combo_report_train_and_test_absent_sets_are_disjoint_from_both():
    report = report_resource_type_risk_label_combos(_SPLIT_DATA)
    test_absent = set(report["combinations_in_test_but_absent_from_train"])
    both = set(report["combinations_in_both"])
    assert test_absent.isdisjoint(both)


def test_combo_report_finds_the_known_unseen_combinations():
    """Regression check pinned to the actual data: for random_state=42,
    the scenario-group split is known (from direct inspection during this
    audit) to leave security_group+Critical and s3_bucket+High entirely
    out of training."""
    report = report_resource_type_risk_label_combos(_SPLIT_DATA)
    assert "security_group + Critical" in report["combinations_in_test_but_absent_from_train"]
    assert "s3_bucket + High" in report["combinations_in_test_but_absent_from_train"]


def test_combo_report_crosstab_has_zero_for_confirmed_missing_combos():
    report = report_resource_type_risk_label_combos(_SPLIT_DATA)
    assert report["train_crosstab"]["security_group"]["Critical"] == 0
    assert report["train_crosstab"]["s3_bucket"]["High"] == 0


# ---------------------------------------------------------------------------
# 5. Unseen combination model impact
# ---------------------------------------------------------------------------

def test_unseen_combo_impact_covers_all_test_scenarios():
    report = report_unseen_combo_model_impact(_SPLIT_DATA)
    test_scenarios = set(report_scenario_groups(_SPLIT_DATA)["test_scenario_ids"])
    assert set(report["random_forest_per_scenario"].keys()) == test_scenarios
    assert set(report["decision_tree_per_scenario"].keys()) == test_scenarios


def test_unseen_combo_impact_accuracy_values_are_valid_fractions():
    report = report_unseen_combo_model_impact(_SPLIT_DATA)
    for model_key in ["random_forest_per_scenario", "decision_tree_per_scenario"]:
        for scenario_id, detail in report[model_key].items():
            acc = detail["accuracy_for_this_scenario"]
            assert acc is None or 0.0 <= acc <= 1.0


def test_unseen_combo_impact_shows_degraded_accuracy_on_unseen_combo_scenarios():
    """The scenarios corresponding to unseen (resource_type, risk_label)
    combos (E1, E2, S3id) should show measurable failure for at least one
    model -- this is the core, verified finding of this audit."""
    report = report_unseen_combo_model_impact(_SPLIT_DATA)
    rf = report["random_forest_per_scenario"]
    for scenario_id in ["E1", "E2", "S3id"]:
        assert rf[scenario_id]["accuracy_for_this_scenario"] < 1.0


# ---------------------------------------------------------------------------
# 6. E7 vs I3/I6 feature sufficiency
# ---------------------------------------------------------------------------

def test_e7_i3_i6_core_severity_features_confirmed_identical():
    report = report_e7_vs_i3_i6_feature_sufficiency()
    assert report["core_severity_signature_identical_between_E7_and_I3_I6"] is True


def test_e7_i3_i6_resource_type_and_port_exposure_do_differ():
    report = report_e7_vs_i3_i6_feature_sufficiency()
    assert "resource_type" in report["features_that_differ_between_E7_and_I3_I6"]
    assert "port_exposure" in report["features_that_differ_between_E7_and_I3_I6"]


def test_e7_holdout_experiment_true_label_is_medium():
    report = report_e7_vs_i3_i6_feature_sufficiency()
    assert report["targeted_holdout_experiment"]["true_label_for_all_E7_records"] == "Medium"


def test_e7_holdout_experiment_correct_rates_are_valid_fractions():
    report = report_e7_vs_i3_i6_feature_sufficiency()
    th = report["targeted_holdout_experiment"]
    assert 0.0 <= th["random_forest_correct_rate"] <= 1.0
    assert 0.0 <= th["decision_tree_correct_rate"] <= 1.0


def test_e7_holdout_experiment_reproducible():
    report_1 = report_e7_vs_i3_i6_feature_sufficiency()
    report_2 = report_e7_vs_i3_i6_feature_sufficiency()
    assert (
        report_1["targeted_holdout_experiment"]["random_forest_correct_rate"]
        == report_2["targeted_holdout_experiment"]["random_forest_correct_rate"]
    )
    assert (
        report_1["targeted_holdout_experiment"]["random_forest_prediction_distribution"]
        == report_2["targeted_holdout_experiment"]["random_forest_prediction_distribution"]
    )


# ---------------------------------------------------------------------------
# 7. changed_attribute encoding check
# ---------------------------------------------------------------------------

def test_changed_attribute_confirmed_in_onehot_transformer():
    report = report_changed_attribute_encoding_check()
    assert report["changed_attribute_is_in_nominal_onehot_transformer"] is True
    assert report["num_onehot_columns_for_changed_attribute"] == 20  # 20 approved scenarios


def test_changed_attribute_value_changes_model_input_for_seen_categories():
    report = report_changed_attribute_encoding_check()
    assert report["seen_category_value_changes_model_input"] is True


def test_changed_attribute_unseen_category_handled_without_corrupting_other_features():
    report = report_changed_attribute_encoding_check()
    assert report["unseen_category_zeroes_only_its_own_onehot_block"] is True
    assert report["unseen_category_other_features_remain_populated"] is True


# ---------------------------------------------------------------------------
# 8. Methodological limitations
# ---------------------------------------------------------------------------

def test_methodological_limitations_covers_all_required_topics():
    report = methodological_limitations_report()
    required_keys = {
        "synthetic_data",
        "scenario_group_split_sensitivity",
        "unseen_resource_type_risk_combinations",
        "balanced_class_distribution",
        "limited_number_of_scenario_groups",
    }
    assert required_keys.issubset(report.keys())
    for key in required_keys:
        assert isinstance(report[key], str)
        assert len(report[key]) > 50  # non-trivial content, not a stub


# ---------------------------------------------------------------------------
# Full audit orchestration
# ---------------------------------------------------------------------------

def test_run_audit_produces_all_required_top_level_sections():
    report = run_audit()
    required_sections = {
        "scenario_group_split",
        "class_distribution",
        "resource_type_risk_label_combinations",
        "unseen_combination_model_impact",
        "e7_vs_i3_i6_feature_sufficiency",
        "changed_attribute_encoding_check",
        "methodological_limitations",
    }
    assert required_sections.issubset(report.keys())


def test_run_audit_is_json_serializable():
    """The report must be writable as-is with json.dump -- catches any
    numpy scalar / non-native type that would otherwise raise."""
    import json
    report = run_audit()
    serialized = json.dumps(report)  # raises TypeError if not serializable
    assert len(serialized) > 0
