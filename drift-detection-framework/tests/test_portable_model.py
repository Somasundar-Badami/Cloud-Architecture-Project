"""
tests/test_portable_model.py

Verifies that models/portable_model.json + src/portable_model.py (the
dependency-free model used inside AWS Lambda) reproduce the saved primary
sklearn pipeline and shap.TreeExplainer numerically, and that the
committed JSON export is in sync with the committed joblib artifacts.

Run with:
    pytest tests/test_portable_model.py -v
"""

import json
import os
import sys

import joblib
import numpy as np
import pytest
import shap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from portable_model import PortableRiskModel, export_portable_model, _sha256  # noqa: E402
from ml_pipeline import load_dataset, FEATURE_COLUMNS, BOOLEAN_FEATURES, DATASET_CSV  # noqa: E402

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
PORTABLE_PATH = os.path.join(MODELS_DIR, "portable_model.json")
RF_PATH = os.path.join(MODELS_DIR, "random_forest_model.joblib")
PRE_PATH = os.path.join(MODELS_DIR, "preprocessor.joblib")
MAPPING_PATH = os.path.join(MODELS_DIR, "label_mapping.json")

TOLERANCE = 1e-12


@pytest.fixture(scope="module")
def portable():
    return PortableRiskModel.load(PORTABLE_PATH)


@pytest.fixture(scope="module")
def sklearn_artifacts():
    return joblib.load(RF_PATH), joblib.load(PRE_PATH)


@pytest.fixture(scope="module")
def dataset_features():
    df = load_dataset(DATASET_CSV)
    X = df[FEATURE_COLUMNS].copy()
    for col in BOOLEAN_FEATURES:
        X[col] = X[col].astype(int)
    return df, X


def _dense(m):
    return m.toarray() if hasattr(m, "toarray") else np.asarray(m)


def test_committed_export_matches_committed_joblib_artifacts():
    with open(PORTABLE_PATH) as f:
        source = json.load(f)["source"]
    assert source["model_sha256"] == _sha256(RF_PATH)
    assert source["preprocessor_sha256"] == _sha256(PRE_PATH)


def test_reexport_is_identical_to_committed_file():
    fresh = export_portable_model(RF_PATH, PRE_PATH, MAPPING_PATH)
    with open(PORTABLE_PATH) as f:
        committed = json.load(f)
    assert fresh == committed


def test_feature_names_match_preprocessor(portable, sklearn_artifacts):
    _, pre = sklearn_artifacts
    assert portable.feature_names == list(pre.get_feature_names_out())
    assert portable.classes == ["Low", "Medium", "High", "Critical"]


def test_transform_matches_preprocessor_on_all_records(portable, sklearn_artifacts, dataset_features):
    _, pre = sklearn_artifacts
    _, X = dataset_features
    expected = _dense(pre.transform(X))
    mine = np.array([portable.transform(r) for r in X.to_dict("records")])
    assert mine.shape == expected.shape
    assert np.array_equal(mine, expected)


def test_predict_proba_matches_sklearn_on_all_records(portable, sklearn_artifacts, dataset_features):
    rf, pre = sklearn_artifacts
    _, X = dataset_features
    Xt = _dense(pre.transform(X))
    expected = rf.predict_proba(Xt)
    mine = np.array([portable.predict_proba(list(row)) for row in Xt])
    assert np.abs(mine - expected).max() < TOLERANCE


def test_shap_values_match_tree_explainer(portable, sklearn_artifacts, dataset_features):
    """Two records per scenario (40 records) -- every scenario is covered."""
    rf, pre = sklearn_artifacts
    df, X = dataset_features
    idx = df.groupby("scenario_id").head(2).index
    Xt = _dense(pre.transform(X.loc[idx]))
    explainer = shap.TreeExplainer(rf)
    expected = np.array(explainer.shap_values(Xt))  # (n, features, classes)
    mine = np.array([portable.shap_values(list(row)) for row in Xt])
    assert mine.shape == expected.shape
    assert np.abs(mine - expected).max() < TOLERANCE
    assert np.abs(np.array(explainer.expected_value) - portable.expected_value()).max() < TOLERANCE


def test_explain_is_additive_and_ranked(portable, dataset_features):
    _, X = dataset_features
    record = X.iloc[0].to_dict()
    result = portable.explain(record)
    assert result["additivity_error"] < 1e-9
    assert result["predicted_label"] in portable.classes
    assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-9
    positives = [v for _, v in result["top_positive_contributors"]]
    negatives = [v for _, v in result["top_negative_contributors"]]
    assert positives == sorted(positives, reverse=True) and all(v > 0 for v in positives)
    assert negatives == sorted(negatives) and all(v < 0 for v in negatives)


def test_unknown_changed_attribute_is_ignored_like_onehot_encoder(portable, sklearn_artifacts, dataset_features):
    _, pre = sklearn_artifacts
    _, X = dataset_features
    row = X.iloc[[0]].copy()
    row["changed_attribute"] = "attribute_never_seen_in_training"
    expected = _dense(pre.transform(row))[0]
    assert portable.transform(row.iloc[0].to_dict()) == list(expected)


def test_unknown_ordinal_value_raises(portable, dataset_features):
    _, X = dataset_features
    record = X.iloc[0].to_dict()
    record["security_sensitivity"] = "Extreme"
    with pytest.raises(ValueError):
        portable.transform(record)


def test_portable_module_has_no_third_party_runtime_imports():
    """The Lambda runtime only has the standard library + boto3."""
    path = os.path.join(os.path.dirname(__file__), "..", "src", "portable_model.py")
    with open(path) as f:
        top_level_imports = [
            line for line in f.read().splitlines()
            if line.startswith("import ") or line.startswith("from ")
        ]
    allowed = {"hashlib", "json", "os", "typing"}
    for line in top_level_imports:
        module = line.split()[1].split(".")[0]
        assert module in allowed, f"unexpected top-level import: {line}"
