"""
tests/test_ml_pipeline.py

Pytest tests for src/ml_pipeline.py.

Covers: dataset loading, preprocessing, expected feature columns, model
training, prediction shape, and reproducibility -- run against the real
data/dataset.csv and the real pipeline functions, not mocks.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from ml_pipeline import (  # noqa: E402
    load_dataset,
    separate_features_target_metadata,
    encode_target,
    build_preprocessor,
    stratified_random_split,
    scenario_group_split,
    describe_split_leakage,
    train_random_forest,
    train_decision_tree,
    evaluate_model,
    run_split,
    FEATURE_COLUMNS,
    METADATA_COLUMNS,
    TARGET_COLUMN,
    RISK_LABEL_ORDER,
)


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def test_load_dataset_returns_dataframe_with_expected_row_count():
    df = load_dataset()
    assert isinstance(df, pd.DataFrame)
    assert 600 <= len(df) <= 900


def test_load_dataset_change_magnitude_none_string_not_corrupted_to_nan():
    """Regression check for the pandas default-NA-parsing pitfall found
    during this milestone: the literal string "None" in change_magnitude
    must survive loading, not become NaN."""
    df = load_dataset()
    assert "None" in df["change_magnitude"].unique()
    assert df["change_magnitude"].isnull().sum() == 0


def test_load_dataset_has_no_missing_values_in_any_column():
    df = load_dataset()
    assert df.isnull().sum().sum() == 0


# ---------------------------------------------------------------------------
# Feature / target / metadata separation
# ---------------------------------------------------------------------------

def test_separate_features_target_metadata_excludes_identifiers():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)

    for excluded_col in ["record_id", "scenario_id", "group_id"]:
        assert excluded_col not in X.columns

    assert set(metadata.columns) == set(METADATA_COLUMNS)


def test_separate_features_target_matches_approved_feature_schema():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)

    expected = {
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
    assert set(X.columns) == expected
    assert set(X.columns) == set(FEATURE_COLUMNS)


def test_target_series_is_risk_label_column():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    assert y.name == TARGET_COLUMN
    assert set(y.unique()) == set(RISK_LABEL_ORDER)


def test_boolean_features_are_cast_to_int():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    for col in ["public_exposure", "encryption_change", "privilege_change"]:
        assert set(X[col].unique()).issubset({0, 1})


def test_no_raw_old_new_value_columns_anywhere_in_X():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    assert "old_value" not in X.columns
    assert "new_value" not in X.columns
    assert "desired_state" not in X.columns
    assert "actual_state" not in X.columns


# ---------------------------------------------------------------------------
# Target encoding
# ---------------------------------------------------------------------------

def test_encode_target_uses_severity_order_not_alphabetical():
    df = load_dataset()
    _, y, _ = separate_features_target_metadata(df)
    y_encoded, mapping, inverse_mapping = encode_target(y)

    assert mapping == {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    assert inverse_mapping == {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}
    assert y_encoded.min() == 0
    assert y_encoded.max() == 3


def test_encode_target_raises_on_unmapped_label():
    bad_series = pd.Series(["Low", "Medium", "NotARealLabel"], name="risk_label")
    with pytest.raises(ValueError):
        encode_target(bad_series)


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def test_preprocessor_fit_transform_produces_numeric_2d_array():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    preprocessor = build_preprocessor()
    X_transformed = preprocessor.fit_transform(X)

    assert X_transformed.ndim == 2
    assert X_transformed.shape[0] == len(X)
    assert np.issubdtype(X_transformed.dtype, np.number)


def test_preprocessor_handles_unseen_category_without_error():
    """Required for the scenario-group-aware split: transform() must not
    raise when a changed_attribute value never appeared during fit."""
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)

    fit_subset = X[X["changed_attribute"] != "block_public_access"]
    unseen_subset = X[X["changed_attribute"] == "block_public_access"]
    assert len(unseen_subset) > 0, "test setup assumption failed"

    preprocessor = build_preprocessor()
    preprocessor.fit(fit_subset)
    # Should not raise, even though 'block_public_access' was never seen.
    result = preprocessor.transform(unseen_subset)
    assert result.shape[0] == len(unseen_subset)


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def test_stratified_random_split_preserves_class_proportions_roughly():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)

    train_idx, test_idx = stratified_random_split(X, y_encoded, test_size=0.2)
    assert len(train_idx) + len(test_idx) == len(X)
    assert len(set(train_idx) & set(test_idx)) == 0  # no row appears in both

    full_props = np.bincount(y_encoded) / len(y_encoded)
    test_props = np.bincount(y_encoded[test_idx]) / len(test_idx)
    assert np.allclose(full_props, test_props, atol=0.05)


def test_stratified_random_split_leaks_scenarios_across_train_and_test():
    """Documents the leakage this milestone was asked to investigate:
    at the record level, the same scenario_id legitimately appears on
    both sides of a plain stratified split."""
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)

    train_idx, test_idx = stratified_random_split(X, y_encoded, test_size=0.2)
    leakage = describe_split_leakage(metadata, train_idx, test_idx)
    assert leakage["num_scenarios_leaked"] > 0


def test_scenario_group_split_has_zero_scenario_leakage():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)

    train_idx, test_idx = scenario_group_split(X, y_encoded, metadata, test_size=0.2)
    leakage = describe_split_leakage(metadata, train_idx, test_idx)
    assert leakage["num_scenarios_leaked"] == 0
    assert len(set(train_idx) & set(test_idx)) == 0


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

def test_random_forest_trains_and_predicts():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)
    preprocessor = build_preprocessor()
    X_transformed = preprocessor.fit_transform(X)

    model = train_random_forest(X_transformed, y_encoded)
    preds = model.predict(X_transformed)
    assert len(preds) == len(y_encoded)
    assert set(preds).issubset({0, 1, 2, 3})


def test_decision_tree_trains_and_predicts():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)
    preprocessor = build_preprocessor()
    X_transformed = preprocessor.fit_transform(X)

    model = train_decision_tree(X_transformed, y_encoded)
    preds = model.predict(X_transformed)
    assert len(preds) == len(y_encoded)


def test_prediction_shape_matches_test_set_size():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)
    train_idx, test_idx = stratified_random_split(X, y_encoded, test_size=0.25)

    preprocessor = build_preprocessor()
    X_train = preprocessor.fit_transform(X.iloc[train_idx])
    X_test = preprocessor.transform(X.iloc[test_idx])

    model = train_random_forest(X_train, y_encoded[train_idx])
    preds = model.predict(X_test)
    assert preds.shape == (len(test_idx),)


def test_evaluate_model_returns_all_required_metrics():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, inverse_mapping = encode_target(y)
    train_idx, test_idx = stratified_random_split(X, y_encoded, test_size=0.2)

    preprocessor = build_preprocessor()
    X_train = preprocessor.fit_transform(X.iloc[train_idx])
    X_test = preprocessor.transform(X.iloc[test_idx])
    model = train_random_forest(X_train, y_encoded[train_idx])

    metrics = evaluate_model(model, X_test, y_encoded[test_idx], inverse_mapping)

    for key in [
        "accuracy", "precision_macro", "recall_macro", "f1_macro",
        "precision_weighted", "recall_weighted", "f1_weighted",
        "confusion_matrix", "confusion_matrix_labels", "classification_report",
    ]:
        assert key in metrics

    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert len(metrics["confusion_matrix"]) == 4  # 4 classes
    assert len(metrics["confusion_matrix"][0]) == 4


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def test_stratified_split_is_reproducible_given_same_seed():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)

    train_idx_1, test_idx_1 = stratified_random_split(X, y_encoded, random_state=42)
    train_idx_2, test_idx_2 = stratified_random_split(X, y_encoded, random_state=42)

    assert np.array_equal(train_idx_1, train_idx_2)
    assert np.array_equal(test_idx_1, test_idx_2)


def test_random_forest_predictions_reproducible_given_same_seed():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)
    train_idx, test_idx = stratified_random_split(X, y_encoded, random_state=42)

    preprocessor = build_preprocessor()
    X_train = preprocessor.fit_transform(X.iloc[train_idx])
    X_test = preprocessor.transform(X.iloc[test_idx])

    model_1 = train_random_forest(X_train, y_encoded[train_idx], random_state=42)
    model_2 = train_random_forest(X_train, y_encoded[train_idx], random_state=42)

    preds_1 = model_1.predict(X_test)
    preds_2 = model_2.predict(X_test)
    assert np.array_equal(preds_1, preds_2)


def test_run_split_end_to_end_is_reproducible():
    """Full run_split() pipeline (preprocess + train + evaluate) must give
    byte-identical metrics across two independent runs with the same seed."""
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)
    train_idx, test_idx = stratified_random_split(X, y_encoded, random_state=42)

    result_1 = run_split(X, y_encoded, metadata, train_idx, test_idx, "test_run_1")
    result_2 = run_split(X, y_encoded, metadata, train_idx, test_idx, "test_run_2")

    assert result_1["random_forest"]["metrics"]["accuracy"] == result_2["random_forest"]["metrics"]["accuracy"]
    assert result_1["decision_tree"]["metrics"]["accuracy"] == result_2["decision_tree"]["metrics"]["accuracy"]
    assert result_1["random_forest"]["metrics"]["confusion_matrix"] == result_2["random_forest"]["metrics"]["confusion_matrix"]
