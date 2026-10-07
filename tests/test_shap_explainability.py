"""
tests/test_shap_explainability.py

Pytest tests for src/shap_explainability.py.

Covers: model loading, transformed feature-name alignment, SHAP output
shape, representative record selection, and saved explanation files.
Runs against the real saved models and real dataset -- no mocks.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from shap_explainability import (  # noqa: E402
    load_models_and_preprocessors,
    load_full_dataset_prepared,
    transform_with_saved_preprocessor,
    verify_feature_name_alignment,
    build_explainer,
    compute_shap_values,
    check_additivity,
    shap_values_for_predicted_class,
    select_representative_records,
    explain_single_record,
    RAW_FEATURE_COLUMNS,
    SHAP_DIR,
)


# Loaded once and reused -- these are read-only artifact loads, not training.
_ARTIFACTS = load_models_and_preprocessors()
_DF, _X, _Y, _Y_ENCODED, _METADATA = load_full_dataset_prepared()


# ---------------------------------------------------------------------------
# Model / preprocessor loading
# ---------------------------------------------------------------------------

def test_primary_models_load_successfully():
    assert _ARTIFACTS["random_forest_primary"] is not None
    assert _ARTIFACTS["decision_tree_primary"] is not None
    assert hasattr(_ARTIFACTS["random_forest_primary"], "predict_proba")
    assert hasattr(_ARTIFACTS["decision_tree_primary"], "predict_proba")


def test_secondary_model_loads_successfully():
    assert _ARTIFACTS["random_forest_secondary"] is not None
    assert hasattr(_ARTIFACTS["random_forest_secondary"], "predict_proba")


def test_preprocessors_load_and_are_already_fitted():
    """An unfitted preprocessor would raise NotFittedError on .transform();
    successfully transforming confirms these were loaded already-fitted,
    not re-fit here."""
    preprocessor = _ARTIFACTS["preprocessor_primary"]
    X_transformed = preprocessor.transform(_X.iloc[:3])
    assert X_transformed.shape[0] == 3


def test_label_mapping_loaded_with_severity_order():
    assert _ARTIFACTS["label_to_int"] == {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    assert _ARTIFACTS["int_to_label"] == {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}


def test_models_are_the_same_objects_saved_by_ml_pipeline_not_retrained():
    """Sanity check: primary model's feature count matches the known
    30-column transformed feature space from prior milestones -- if this
    module had accidentally retrained on a different feature set, this
    would fail."""
    rf = _ARTIFACTS["random_forest_primary"]
    assert rf.n_features_in_ == 30


# ---------------------------------------------------------------------------
# Transformed feature-name alignment
# ---------------------------------------------------------------------------

def test_feature_name_alignment_passes_for_primary_preprocessor():
    X_transformed, feature_names = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X)
    alignment = verify_feature_name_alignment(X_transformed, feature_names)
    assert alignment["aligned"] is True
    assert alignment["n_transformed_columns"] == alignment["n_feature_names"]


def test_feature_names_are_non_empty_strings_in_expected_order():
    _, feature_names = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X)
    assert len(feature_names) == 30
    assert all(isinstance(f, str) and len(f) > 0 for f in feature_names)
    # Ordinal columns must come first (ColumnTransformer preserves
    # transformer definition order), confirmed by exact expected prefix.
    assert feature_names[0].startswith("ordinal__")


def test_feature_name_alignment_holds_for_secondary_preprocessor_too():
    X_transformed, feature_names = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_secondary"], _X)
    alignment = verify_feature_name_alignment(X_transformed, feature_names)
    assert alignment["aligned"] is True


# ---------------------------------------------------------------------------
# SHAP output shape
# ---------------------------------------------------------------------------

def test_shap_values_shape_matches_samples_features_classes():
    X_transformed, feature_names = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X.iloc[:10])
    explainer = build_explainer(_ARTIFACTS["random_forest_primary"])
    shap_values, base_values = compute_shap_values(explainer, X_transformed)

    assert shap_values.shape == (10, len(feature_names), 4)
    assert base_values.shape == (4,)


def test_shap_values_shape_consistent_for_decision_tree():
    X_transformed, feature_names = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X.iloc[:10])
    explainer = build_explainer(_ARTIFACTS["decision_tree_primary"])
    shap_values, base_values = compute_shap_values(explainer, X_transformed)

    assert shap_values.shape == (10, len(feature_names), 4)


def test_additivity_holds_within_tight_tolerance_for_random_forest():
    X_transformed, _ = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X.iloc[:30])
    explainer = build_explainer(_ARTIFACTS["random_forest_primary"])
    shap_values, base_values = compute_shap_values(explainer, X_transformed)
    result = check_additivity(shap_values, base_values, _ARTIFACTS["random_forest_primary"], X_transformed)
    assert result["additivity_holds"] is True
    assert result["max_abs_diff_from_predict_proba"] < 1e-6


def test_additivity_holds_for_decision_tree():
    X_transformed, _ = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X.iloc[:30])
    explainer = build_explainer(_ARTIFACTS["decision_tree_primary"])
    shap_values, base_values = compute_shap_values(explainer, X_transformed)
    result = check_additivity(shap_values, base_values, _ARTIFACTS["decision_tree_primary"], X_transformed)
    assert result["additivity_holds"] is True


def test_shap_values_for_predicted_class_selects_correct_slice():
    X_transformed, _ = transform_with_saved_preprocessor(_ARTIFACTS["preprocessor_primary"], _X.iloc[:5])
    explainer = build_explainer(_ARTIFACTS["random_forest_primary"])
    shap_values, _ = compute_shap_values(explainer, X_transformed)

    predicted = _ARTIFACTS["random_forest_primary"].predict(X_transformed)
    selected = shap_values_for_predicted_class(shap_values, predicted)

    assert selected.shape == (5, shap_values.shape[1])
    # Manually verify one row matches the correct class slice exactly.
    for i in range(5):
        assert np.array_equal(selected[i], shap_values[i, :, predicted[i]])


# ---------------------------------------------------------------------------
# Representative record selection
# ---------------------------------------------------------------------------

def test_representative_records_all_have_valid_row_indices():
    selections = select_representative_records(_DF, _ARTIFACTS)
    for key in [
        "critical_security_group_public_exposure",
        "high_iam_privilege_change",
        "medium_e7_case",
        "low_e5_no_drift_control",
        "correctly_classified",
        "incorrectly_classified",
    ]:
        idx = selections[key]["row_index"]
        assert idx in _DF.index


def test_critical_security_group_selection_matches_its_own_criteria():
    selections = select_representative_records(_DF, _ARTIFACTS)
    idx = selections["critical_security_group_public_exposure"]["row_index"]
    row = _DF.loc[idx]
    assert row["resource_type"] == "security_group"
    assert row["risk_label"] == "Critical"
    assert bool(row["public_exposure"]) is True


def test_high_iam_selection_matches_its_own_criteria():
    selections = select_representative_records(_DF, _ARTIFACTS)
    idx = selections["high_iam_privilege_change"]["row_index"]
    row = _DF.loc[idx]
    assert row["resource_type"] == "iam_policy"
    assert row["risk_label"] == "High"
    assert bool(row["privilege_change"]) is True


def test_e7_and_e5_selections_have_correct_scenario_id():
    selections = select_representative_records(_DF, _ARTIFACTS)
    e7_idx = selections["medium_e7_case"]["row_index"]
    e5_idx = selections["low_e5_no_drift_control"]["row_index"]
    assert _DF.loc[e7_idx, "scenario_id"] == "E7"
    assert _DF.loc[e5_idx, "scenario_id"] == "E5"


def test_incorrectly_classified_selection_is_genuinely_incorrect():
    """The selected 'incorrect' record must actually be misclassified by
    whichever model it's paired with -- not just labeled as such."""
    selections = select_representative_records(_DF, _ARTIFACTS)
    sel = selections["incorrectly_classified"]
    idx = sel["row_index"]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_secondary"], _ARTIFACTS["preprocessor_secondary"],
        _ARTIFACTS["int_to_label"],
    )
    assert explanation["prediction_correct"] is False
    assert explanation["actual_label"] != explanation["predicted_label"]


def test_correctly_classified_selection_is_genuinely_correct():
    selections = select_representative_records(_DF, _ARTIFACTS)
    sel = selections["correctly_classified"]
    idx = sel["row_index"]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_primary"], _ARTIFACTS["preprocessor_primary"],
        _ARTIFACTS["int_to_label"],
    )
    assert explanation["prediction_correct"] is True


def test_selection_diagnostics_confirms_primary_model_has_zero_errors():
    """Regression check pinned to the documented finding: the primary
    model has zero misclassifications across the full dataset, which is
    WHY the secondary model is used for the 'incorrect' example."""
    selections = select_representative_records(_DF, _ARTIFACTS)
    assert selections["diagnostics"]["primary_model_full_dataset_mismatches"] == 0


def test_selection_is_reproducible():
    selections_1 = select_representative_records(_DF, _ARTIFACTS)
    selections_2 = select_representative_records(_DF, _ARTIFACTS)
    for key in ["critical_security_group_public_exposure", "medium_e7_case", "incorrectly_classified"]:
        assert selections_1[key]["row_index"] == selections_2[key]["row_index"]


# ---------------------------------------------------------------------------
# explain_single_record structural checks
# ---------------------------------------------------------------------------

def test_explain_single_record_returns_all_required_fields():
    idx = _DF.index[0]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_primary"], _ARTIFACTS["preprocessor_primary"],
        _ARTIFACTS["int_to_label"],
    )
    required_keys = {
        "row_index", "scenario_id", "actual_label", "predicted_label",
        "prediction_correct", "prediction_probabilities",
        "shap_values_correspond_to_class", "additivity_check",
        "top_positive_contributors", "top_negative_contributors",
        "all_shap_values_for_predicted_class", "original_feature_values",
    }
    assert required_keys.issubset(explanation.keys())


def test_explain_single_record_original_feature_values_match_raw_schema():
    idx = _DF.index[0]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_primary"], _ARTIFACTS["preprocessor_primary"],
        _ARTIFACTS["int_to_label"],
    )
    assert set(explanation["original_feature_values"].keys()) == set(RAW_FEATURE_COLUMNS)


def test_explain_single_record_shap_values_correspond_to_predicted_class():
    idx = _DF.index[0]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_primary"], _ARTIFACTS["preprocessor_primary"],
        _ARTIFACTS["int_to_label"],
    )
    assert explanation["shap_values_correspond_to_class"] == explanation["predicted_label"]


def test_explain_single_record_probabilities_sum_to_one():
    idx = _DF.index[0]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_primary"], _ARTIFACTS["preprocessor_primary"],
        _ARTIFACTS["int_to_label"],
    )
    total = sum(explanation["prediction_probabilities"].values())
    assert abs(total - 1.0) < 1e-6


def test_explain_single_record_is_json_serializable():
    idx = _DF.index[0]
    explanation = explain_single_record(
        idx, _DF, _X, _Y_ENCODED,
        _ARTIFACTS["random_forest_primary"], _ARTIFACTS["preprocessor_primary"],
        _ARTIFACTS["int_to_label"],
    )
    serialized = json.dumps(explanation)
    assert len(serialized) > 0


# ---------------------------------------------------------------------------
# Saved explanation files (assumes run_shap_milestone() has been run once;
# skips gracefully if artifacts are not yet present rather than failing the
# whole suite on ordering).
# ---------------------------------------------------------------------------

REQUIRED_SHAP_FILES = [
    "global_summary.png",
    "global_bar.png",
    "local_critical.png",
    "local_iam_high.png",
    "local_e7_medium.png",
    "local_e5_low.png",
    "local_correct.png",
    "local_incorrect.png",
    "global_feature_importance.json",
    "local_explanations.json",
]


@pytest.fixture(scope="module", autouse=True)
def ensure_shap_artifacts_exist():
    """Runs the full SHAP milestone once if artifacts aren't already on
    disk, so this test file is runnable standalone as well as after
    shap_explainability.py has already been run manually."""
    missing = [f for f in REQUIRED_SHAP_FILES if not os.path.exists(os.path.join(SHAP_DIR, f))]
    if missing:
        from shap_explainability import run_shap_milestone
        run_shap_milestone()


@pytest.mark.parametrize("filename", REQUIRED_SHAP_FILES)
def test_required_shap_output_file_exists_and_nonempty(filename):
    path = os.path.join(SHAP_DIR, filename)
    assert os.path.exists(path), f"Missing required SHAP output file: {filename}"
    assert os.path.getsize(path) > 0


def test_global_feature_importance_json_has_required_structure():
    with open(os.path.join(SHAP_DIR, "global_feature_importance.json")) as f:
        data = json.load(f)
    assert "mean_abs_shap_overall_across_all_classes" in data
    assert "mean_abs_shap_by_class" in data
    assert set(data["mean_abs_shap_by_class"].keys()) == {"Low", "Medium", "High", "Critical"}
    assert data["additivity_check"]["additivity_holds"] is True


def test_local_explanations_json_has_all_six_cases():
    with open(os.path.join(SHAP_DIR, "local_explanations.json")) as f:
        data = json.load(f)
    required_cases = {
        "critical_security_group_public_exposure",
        "high_iam_privilege_change",
        "medium_e7_case",
        "low_e5_no_drift_control",
        "correctly_classified",
        "incorrectly_classified",
    }
    assert required_cases.issubset(data.keys())


def test_local_explanations_correct_and_incorrect_cases_have_expected_correctness():
    with open(os.path.join(SHAP_DIR, "local_explanations.json")) as f:
        data = json.load(f)
    assert data["correctly_classified"]["prediction_correct"] is True
    assert data["incorrectly_classified"]["prediction_correct"] is False
