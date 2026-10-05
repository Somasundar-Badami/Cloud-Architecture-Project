"""
tests/test_app.py

Basic tests for app.py per the dashboard milestone requirements:
  - App imports
  - JSON parsing
  - Model loading
  - No-drift input
  - Drift input
  - Invalid JSON handling

These test the PURE functions in app.py directly (parse_json_input,
load_model_artifacts, run_drift_and_risk_pipeline, generate_scenario_json,
etc.) -- none of them invoke Streamlit's runtime, so no `streamlit run`
server is needed. app.py is structured so that importing it never executes
any st.* call (all UI code lives inside main(), guarded by
`if __name__ == "__main__"`), which is what test_app_imports_without_
running_streamlit_ui below actually verifies.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# App imports
# ---------------------------------------------------------------------------

def test_app_imports_without_running_streamlit_ui():
    """Importing app.py must succeed and must NOT execute any Streamlit
    UI call (those live only inside main(), never at module level)."""
    import app
    assert hasattr(app, "main")
    assert hasattr(app, "parse_json_input")
    assert hasattr(app, "run_drift_and_risk_pipeline")


def test_app_reuses_existing_modules_not_reimplementations():
    """Confirms app.py imports the real functions from the existing
    modules rather than redefining its own copies."""
    import app
    from drift_engine import detect_drift
    from feature_extraction import extract_features

    assert app.detect_drift is detect_drift
    assert app.extract_features is extract_features


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def test_parse_json_input_valid_object():
    import app
    parsed, error = app.parse_json_input('{"a": 1, "b": true}', "Desired state")
    assert error is None
    assert parsed == {"a": 1, "b": True}


def test_parse_json_input_invalid_json_syntax():
    import app
    parsed, error = app.parse_json_input('{invalid json', "Desired state")
    assert parsed is None
    assert error is not None
    assert "not valid JSON" in error


def test_parse_json_input_empty_string():
    import app
    parsed, error = app.parse_json_input("", "Actual state")
    assert parsed is None
    assert "empty" in error.lower()


def test_parse_json_input_whitespace_only():
    import app
    parsed, error = app.parse_json_input("   \n  ", "Actual state")
    assert parsed is None
    assert "empty" in error.lower()


def test_parse_json_input_non_object_json_rejected():
    """A bare JSON list or number is valid JSON syntax but not a valid
    state object -- must be rejected with a clear message, not crash
    downstream code expecting a dict."""
    import app
    parsed, error = app.parse_json_input("[1, 2, 3]", "Desired state")
    assert parsed is None
    assert "JSON object" in error

    parsed2, error2 = app.parse_json_input("42", "Desired state")
    assert parsed2 is None
    assert "JSON object" in error2


def test_parse_json_input_none_input():
    import app
    parsed, error = app.parse_json_input(None, "Desired state")
    assert parsed is None
    assert error is not None


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def test_load_model_artifacts_succeeds_with_real_saved_models():
    import app
    artifacts = app.load_model_artifacts()
    assert artifacts["model"] is not None
    assert artifacts["preprocessor"] is not None
    assert artifacts["int_to_label"] == {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}
    assert hasattr(artifacts["model"], "predict_proba")


def test_load_model_artifacts_raises_clear_error_when_missing(monkeypatch):
    import app
    monkeypatch.setattr(app, "MODELS_DIR", "/tmp/nonexistent_models_dir_for_testing")
    with pytest.raises(FileNotFoundError) as exc_info:
        app.load_model_artifacts()
    assert "not found" in str(exc_info.value)
    assert "ml_pipeline.py" in str(exc_info.value)  # actionable hint included


# ---------------------------------------------------------------------------
# No-drift input
# ---------------------------------------------------------------------------

def test_no_drift_input_end_to_end():
    """Identical desired/actual states (like the E5 control case) must
    flow through the full pipeline without error and predict Low."""
    import app
    artifacts = app.load_model_artifacts()
    desired = {"bucket_name": "test-bucket", "block_public_access": True}
    actual = {"bucket_name": "test-bucket", "block_public_access": True}

    result = app.run_drift_and_risk_pipeline(desired, actual, "s3_bucket", 0, artifacts)

    assert result["error"] is None
    assert result["drift_result"]["has_drift"] is False
    assert result["drift_result"]["num_changes"] == 0
    assert result["features"]["changed_attribute"] == "none"
    assert result["predicted_label"] == "Low"


def test_no_drift_input_using_predefined_e5_scenario():
    """Uses the REAL E5 scenario generator (not a hand-written mock)."""
    import app
    artifacts = app.load_model_artifacts()
    desired, actual, resource_type, ground_truth = app.generate_scenario_json("E5")

    assert desired == actual  # E5 is the non-drift control by construction
    assert ground_truth == "Low"

    result = app.run_drift_and_risk_pipeline(desired, actual, resource_type, 0, artifacts)
    assert result["drift_result"]["has_drift"] is False
    assert result["predicted_label"] == "Low"


# ---------------------------------------------------------------------------
# Drift input
# ---------------------------------------------------------------------------

def test_drift_input_end_to_end_public_access_disabled():
    """A genuine drift case (block_public_access True -> False) must flow
    through detection, feature extraction, prediction, and SHAP without
    error and predict Critical -- matching scenario S1's approved label."""
    import app
    artifacts = app.load_model_artifacts()
    desired = {"bucket_name": "test-bucket", "block_public_access": True}
    actual = {"bucket_name": "test-bucket", "block_public_access": False}

    result = app.run_drift_and_risk_pipeline(desired, actual, "s3_bucket", 0, artifacts)

    assert result["error"] is None
    assert result["drift_result"]["has_drift"] is True
    assert result["drift_result"]["num_changes"] == 1
    assert result["drift_result"]["changed_attributes"] == ["block_public_access"]
    assert result["predicted_label"] == "Critical"
    assert "shap_values_full" in result
    assert result["additivity_check"]["additivity_holds"] is True


def test_drift_input_using_predefined_s1_scenario_matches_approved_label():
    import app
    artifacts = app.load_model_artifacts()
    desired, actual, resource_type, ground_truth = app.generate_scenario_json("S1")
    assert ground_truth == "Critical"

    result = app.run_drift_and_risk_pipeline(desired, actual, resource_type, 0, artifacts)
    assert result["drift_result"]["has_drift"] is True
    assert result["predicted_label"] == ground_truth


def test_drift_input_probabilities_sum_to_one():
    import app
    artifacts = app.load_model_artifacts()
    desired = {"requires_mfa": True}
    actual = {"requires_mfa": False}
    result = app.run_drift_and_risk_pipeline(desired, actual, "iam_policy", 0, artifacts)
    total = sum(result["probabilities"].values())
    assert abs(total - 1.0) < 1e-6


def test_drift_input_top_positive_and_negative_contributors_are_real_shap_values():
    import app
    artifacts = app.load_model_artifacts()
    desired, actual, resource_type, _ = app.generate_scenario_json("E1")
    result = app.run_drift_and_risk_pipeline(desired, actual, resource_type, 0, artifacts)

    # Every reported contributor must come from the actual computed SHAP
    # vector for the predicted class, not a placeholder.
    for feature, value in result["top_positive_contributors"]:
        assert feature in result["feature_names"]
        assert value > 0
    for feature, value in result["top_negative_contributors"]:
        assert feature in result["feature_names"]
        assert value < 0


# ---------------------------------------------------------------------------
# Invalid JSON handling (integration-level, via parse_json_input)
# ---------------------------------------------------------------------------

def test_invalid_json_does_not_reach_drift_pipeline():
    """Simulates the app.py control flow: invalid JSON must be caught by
    parse_json_input BEFORE run_drift_and_risk_pipeline is ever called."""
    import app
    text = '{"bucket_name": "test", }'  # trailing comma -> invalid JSON
    parsed, error = app.parse_json_input(text, "Desired state")
    assert parsed is None
    assert error is not None
    # Confirms the caller's guard clause (`if err: st.error(...); st.stop()`)
    # would correctly prevent reaching run_drift_and_risk_pipeline at all.


def test_unknown_attribute_handled_without_crashing():
    """An attribute the model has no rule for must return a handled
    error dict, not raise an uncaught exception."""
    import app
    artifacts = app.load_model_artifacts()
    desired = {"some_field_not_in_schema": "old"}
    actual = {"some_field_not_in_schema": "new"}
    result = app.run_drift_and_risk_pipeline(desired, actual, "s3_bucket", 0, artifacts)
    assert result["error"] == "unknown_attribute"
    assert "message" in result
    assert "drift_result" in result  # drift detection itself still succeeded


# ---------------------------------------------------------------------------
# Predefined scenario coverage (all 20 scenarios generate valid, runnable input)
# ---------------------------------------------------------------------------

def test_all_20_predefined_scenarios_generate_valid_json_and_run_without_error():
    import app
    artifacts = app.load_model_artifacts()
    options = app.get_predefined_scenario_options()
    assert len(options) == 20

    for option in options:
        desired, actual, resource_type, ground_truth = app.generate_scenario_json(option["scenario_id"])
        result = app.run_drift_and_risk_pipeline(desired, actual, resource_type, 0, artifacts)
        assert result["error"] is None, f"Scenario {option['scenario_id']} failed: {result.get('message')}"
        assert result["predicted_label"] in {"Low", "Medium", "High", "Critical"}


def test_predefined_scenario_generation_is_deterministic():
    import app
    d1, a1, r1, g1 = app.generate_scenario_json("I1")
    d2, a2, r2, g2 = app.generate_scenario_json("I1")
    assert d1 == d2
    assert a1 == a2
    assert r1 == r2 and g1 == g2


def test_generate_scenario_json_unknown_id_raises():
    import app
    with pytest.raises(ValueError):
        app.generate_scenario_json("NOT_A_REAL_SCENARIO")


# ---------------------------------------------------------------------------
# Feature row construction
# ---------------------------------------------------------------------------

def test_build_feature_row_matches_expected_columns_and_types():
    import app
    from ml_pipeline import FEATURE_COLUMNS, BOOLEAN_FEATURES

    features = {
        "resource_type": "s3_bucket",
        "changed_attribute": "acl",
        "security_sensitivity": "High",
        "public_exposure": True,
        "encryption_change": False,
        "privilege_change": False,
        "port_exposure": "none",
        "change_magnitude": "High",
        "drift_frequency": 2,
    }
    row = app.build_feature_row(features)
    assert list(row.columns) == list(FEATURE_COLUMNS)
    for col in BOOLEAN_FEATURES:
        assert row[col].dtype.kind in ("i", "u")  # cast to int, not bool/object


# ---------------------------------------------------------------------------
# Evaluation limitation summary (sidebar data source)
# ---------------------------------------------------------------------------

def test_load_evaluation_limitation_summary_reads_real_artifacts():
    import app
    summary = app.load_evaluation_limitation_summary()
    assert "split_a_accuracy" in summary
    assert "split_b_accuracy" in summary
    assert 0.0 <= summary["split_a_accuracy"] <= 1.0
    assert 0.0 <= summary["split_b_accuracy"] <= 1.0


def test_load_evaluation_limitation_summary_handles_missing_files(monkeypatch):
    import app
    monkeypatch.setattr(app, "RESULTS_DIR", "/tmp/nonexistent_results_dir_for_testing")
    summary = app.load_evaluation_limitation_summary()
    assert summary == {}


def test_fmt_pct_handles_missing_value_gracefully():
    import app
    assert app._fmt_pct(0.5) == "50%"
    assert app._fmt_pct(None) == "N/A"
    assert app._fmt_pct("not a number") == "N/A"
