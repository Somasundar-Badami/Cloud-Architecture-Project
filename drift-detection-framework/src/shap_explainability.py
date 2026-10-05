"""
shap_explainability.py

SHAP explainability layer on top of the already-trained, already-saved
models. Does NOT retrain any model and does NOT modify the dataset.
Loads models/preprocessors via joblib and reuses the EXACT fitted
preprocessing pipeline from training (preprocessor.transform(), never
.fit_transform()).

Primary model for the main demonstration: Random Forest (Split A,
models/random_forest_model.joblib), per requirement 3.

One documented, deliberate exception to "primary model only": the primary
model achieves 0 misclassifications across the entire 711-record dataset
(verified below, consistent with the previously-documented Split A
leakage/memorization finding) -- so there is no genuine misclassified
record available from it to use as the "incorrectly classified" local
explanation example. That example is sourced from the already-saved
SECONDARY model (models/random_forest_model_scenario_split.joblib, from
the scenario-group-aware split, which has 75 real misclassifications) --
no retraining performed, and this substitution is explicitly labeled in
every output that uses it.

DOCUMENTED SHAP API COMPATIBILITY ISSUE (shap==0.52.0):
  shap.TreeExplainer(model).shap_values(X) for a 4-class sklearn
  RandomForestClassifier/DecisionTreeClassifier returns a single ndarray
  of shape (n_samples, n_features, n_classes) -- NOT the list-of-arrays
  format documented in older SHAP tutorials.
  Passing this 3D array directly to the legacy shap.summary_plot(...)
  with its DEFAULT plot type ("dot"/beeswarm) silently misinterprets it
  as a SHAP-INTERACTION-VALUES array and produces an incorrect,
  misleading plot (confirmed by direct inspection during development --
  see README). plot_type="bar" DOES handle the 3D array correctly
  (produces a correct per-class stacked bar chart) and is used for
  global_bar.png. For the beeswarm (global_summary.png), this module
  uses the modern object API instead: wrap the raw arrays in a
  shap.Explanation, index a single class explicitly
  (explanation[:, :, class_index]), and call shap.plots.beeswarm() on
  that -- confirmed correct by direct inspection.
"""

import os
import json

import joblib
import numpy as np
import pandas as pd
import shap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys
sys.path.insert(0, os.path.dirname(__file__))
from ml_pipeline import (  # noqa: E402
    load_dataset,
    separate_features_target_metadata,
    encode_target,
    stratified_random_split,
    RISK_LABEL_ORDER,
)

_THIS_DIR = os.path.dirname(__file__)
MODELS_DIR = os.path.join(_THIS_DIR, "..", "models")
RESULTS_DIR = os.path.join(_THIS_DIR, "..", "results")
SHAP_DIR = os.path.join(RESULTS_DIR, "shap")

SHAP_VERSION = shap.__version__


# ---------------------------------------------------------------------------
# 1-2. Load artifacts (no retraining)
# ---------------------------------------------------------------------------

def load_models_and_preprocessors():
    """
    Loads the PRIMARY (Split A) Random Forest + Decision Tree models and
    preprocessor, plus the SECONDARY (Split B, scenario-group-aware)
    Random Forest model + its own preprocessor -- the secondary model is
    loaded only to source a genuine misclassification example (see module
    docstring), not used for the main demonstration.
    """
    artifacts = {
        "random_forest_primary": joblib.load(os.path.join(MODELS_DIR, "random_forest_model.joblib")),
        "decision_tree_primary": joblib.load(os.path.join(MODELS_DIR, "decision_tree_model.joblib")),
        "preprocessor_primary": joblib.load(os.path.join(MODELS_DIR, "preprocessor.joblib")),
        "random_forest_secondary": joblib.load(os.path.join(MODELS_DIR, "random_forest_model_scenario_split.joblib")),
        "preprocessor_secondary": joblib.load(os.path.join(MODELS_DIR, "preprocessor_scenario_split.joblib")),
    }
    with open(os.path.join(MODELS_DIR, "label_mapping.json")) as f:
        label_mapping = json.load(f)
    artifacts["label_to_int"] = label_mapping["label_to_int"]
    artifacts["int_to_label"] = {int(k): v for k, v in label_mapping["int_to_label"].items()}
    return artifacts


def load_full_dataset_prepared():
    """Loads data/dataset.csv (unmodified) and separates features/target/metadata."""
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, label_mapping, inverse_mapping = encode_target(y)
    return df, X, y, y_encoded, metadata


# ---------------------------------------------------------------------------
# 5-6. Preprocessing + feature-name alignment (verification, not re-fitting)
# ---------------------------------------------------------------------------

def transform_with_saved_preprocessor(preprocessor, X):
    """
    Applies an ALREADY-FITTED preprocessor via .transform() only.
    Never calls .fit() or .fit_transform() here -- reusing the exact
    pipeline fitted during training is the whole point of this check.
    """
    X_transformed = preprocessor.transform(X)
    feature_names = list(preprocessor.get_feature_names_out())
    return X_transformed, feature_names


def verify_feature_name_alignment(X_transformed, feature_names):
    """
    Confirms the number of transformed columns matches the number of
    feature names 1:1 -- the alignment that every downstream SHAP index
    (shap_values[:, i, :] <-> feature_names[i]) depends on.
    """
    return {
        "n_transformed_columns": int(X_transformed.shape[1]),
        "n_feature_names": len(feature_names),
        "aligned": X_transformed.shape[1] == len(feature_names),
    }


# ---------------------------------------------------------------------------
# 3-4. TreeExplainer + SHAP value computation
# ---------------------------------------------------------------------------

def build_explainer(model):
    """TreeExplainer is supported for both RandomForestClassifier and
    DecisionTreeClassifier (verified during development -- both return a
    (n_samples, n_features, n_classes) array with exact additivity)."""
    return shap.TreeExplainer(model)


def compute_shap_values(explainer, X_transformed):
    """
    Returns shap_values with shape (n_samples, n_features, n_classes) and
    base_values (expected_value) with shape (n_classes,).

    Handles both the modern ndarray return (shap>=~0.45) and the legacy
    list-of-per-class-arrays return (older shap), normalizing to the
    modern (n, f, c) ndarray shape either way so the rest of this module
    can rely on one consistent format.
    """
    raw = explainer.shap_values(X_transformed)
    base_values = np.array(explainer.expected_value)

    if isinstance(raw, list):
        # Legacy shap: list of (n_samples, n_features) arrays, one per class.
        shap_values = np.stack(raw, axis=-1)
    else:
        shap_values = np.array(raw)

    return shap_values, base_values


def check_additivity(shap_values, base_values, model, X_transformed, atol=1e-6):
    """
    Verifies base_value[c] + sum_features(shap_values[:, :, c]) equals the
    model's predict_proba for class c, for every sample and class. This is
    the additivity property SHAP guarantees for tree explainers in
    probability output mode; checking it directly (rather than assuming
    it) is what requirement 'Check additivity where applicable' asks for.
    """
    proba = model.predict_proba(X_transformed)
    reconstructed = base_values[None, :] + shap_values.sum(axis=1)
    max_abs_diff = float(np.abs(reconstructed - proba).max())
    return {
        "max_abs_diff_from_predict_proba": max_abs_diff,
        "additivity_holds": max_abs_diff < atol,
        "tolerance_used": atol,
    }


def shap_values_for_predicted_class(shap_values, predicted_class_indices):
    """
    Requirement: 'Verify that SHAP values correspond to the predicted
    class.' Selects, for each sample, the (n_features,) SHAP vector for
    THAT SAMPLE'S OWN predicted class -- not a fixed class index.
    """
    n_samples = shap_values.shape[0]
    return np.stack([shap_values[i, :, predicted_class_indices[i]] for i in range(n_samples)], axis=0)


# ---------------------------------------------------------------------------
# A. Global explanations
# ---------------------------------------------------------------------------

def compute_global_feature_importance(shap_values, feature_names, inverse_mapping):
    """Mean absolute SHAP importance per feature, both per-class and
    averaged across all classes."""
    n_classes = shap_values.shape[2]
    mean_abs_by_class = {}
    for c in range(n_classes):
        label = inverse_mapping[c]
        mean_abs = np.abs(shap_values[:, :, c]).mean(axis=0)
        ranked = sorted(zip(feature_names, mean_abs.tolist()), key=lambda p: -p[1])
        mean_abs_by_class[label] = [{"feature": f, "mean_abs_shap": v} for f, v in ranked]

    overall_mean_abs = np.abs(shap_values).mean(axis=(0, 2))  # average over samples AND classes
    overall_ranked = sorted(zip(feature_names, overall_mean_abs.tolist()), key=lambda p: -p[1])
    overall = [{"feature": f, "mean_abs_shap": v} for f, v in overall_ranked]

    return {
        "mean_abs_shap_overall_across_all_classes": overall,
        "mean_abs_shap_by_class": mean_abs_by_class,
    }


def plot_global_beeswarm(shap_values, base_values, X_transformed, feature_names, class_index, class_label, out_path):
    """
    Beeswarm for ONE explicitly chosen class (Critical, the operationally
    most important class), using the modern shap.Explanation +
    shap.plots.beeswarm API -- NOT the legacy summary_plot default, which
    was confirmed during development to misinterpret the 3D multiclass
    array as interaction values (see module docstring).
    """
    explanation = shap.Explanation(
        values=shap_values,
        base_values=np.tile(base_values, (shap_values.shape[0], 1)),
        data=X_transformed,
        feature_names=feature_names,
    )
    fig = plt.figure()
    shap.plots.beeswarm(explanation[:, :, class_index], show=False)
    plt.title(f"SHAP Beeswarm — {class_label} class (Random Forest, primary model)", fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_global_bar(shap_values, X_transformed, feature_names, class_names, out_path):
    """
    Stacked per-class bar chart via the legacy summary_plot(plot_type='bar'),
    which WAS confirmed during development to correctly handle the 3D
    multiclass array (unlike the default dot/beeswarm mode).
    """
    fig = plt.figure()
    shap.summary_plot(
        shap_values, X_transformed, feature_names=feature_names,
        plot_type="bar", class_names=class_names, show=False,
    )
    plt.title("Mean |SHAP value| by feature, stacked by class (Random Forest, primary model)", fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# B. Representative record selection (rule-based, verifiable, not hand-picked
#    by row number)
# ---------------------------------------------------------------------------

def select_representative_records(df, artifacts):
    """
    Selects representative record indices (into the full df/X, index-
    aligned) for each required local explanation case, by explicit,
    checkable filter conditions -- not by manually chosen row numbers.
    """
    def _first_index(mask):
        matches = df.index[mask]
        assert len(matches) > 0, "No matching record found for this selection rule"
        return int(matches[0])

    critical_sg_idx = _first_index(
        (df["resource_type"] == "security_group")
        & (df["risk_label"] == "Critical")
        & (df["public_exposure"] == True)  # noqa: E712
    )
    iam_high_idx = _first_index(
        (df["resource_type"] == "iam_policy")
        & (df["risk_label"] == "High")
        & (df["privilege_change"] == True)  # noqa: E712
    )
    e7_medium_idx = _first_index(df["scenario_id"] == "E7")
    e5_low_idx = _first_index(df["scenario_id"] == "E5")

    # "Correct" example: any record from the PRIMARY model's Split A TEST
    # set (genuine held-out prediction, not just a training-fit row).
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, _, _ = encode_target(y)
    _, test_idx_a = stratified_random_split(X, y_encoded, random_state=42)
    X_test_a = X.iloc[test_idx_a]
    X_test_a_transformed = artifacts["preprocessor_primary"].transform(X_test_a)
    preds_test_a = artifacts["random_forest_primary"].predict(X_test_a_transformed)
    correct_mask = preds_test_a == y_encoded[test_idx_a]
    correct_idx = int(test_idx_a[np.where(correct_mask)[0][0]])
    primary_test_accuracy = float(correct_mask.mean())

    # "Incorrect" example: sourced from the SAVED secondary (Split B) model,
    # since the primary model has zero misclassifications dataset-wide
    # (verified below) -- documented substitution, no retraining performed.
    X_all_transformed_secondary = artifacts["preprocessor_secondary"].transform(X)
    preds_secondary_full = artifacts["random_forest_secondary"].predict(X_all_transformed_secondary)
    incorrect_mask = preds_secondary_full != y_encoded
    incorrect_idx = int(np.where(incorrect_mask)[0][0])

    # Confirm (not assume) the primary model really has zero errors dataset-wide,
    # so the substitution above is justified rather than a convenience shortcut.
    X_all_transformed_primary = artifacts["preprocessor_primary"].transform(X)
    preds_primary_full = artifacts["random_forest_primary"].predict(X_all_transformed_primary)
    primary_full_mismatches = int((preds_primary_full != y_encoded).sum())

    return {
        "critical_security_group_public_exposure": {"row_index": critical_sg_idx, "model": "primary"},
        "high_iam_privilege_change": {"row_index": iam_high_idx, "model": "primary"},
        "medium_e7_case": {"row_index": e7_medium_idx, "model": "primary"},
        "low_e5_no_drift_control": {"row_index": e5_low_idx, "model": "primary"},
        "correctly_classified": {"row_index": correct_idx, "model": "primary", "source": "split_A_test_set"},
        "incorrectly_classified": {"row_index": incorrect_idx, "model": "secondary", "source": "split_B_scenario_group_aware"},
        "diagnostics": {
            "primary_model_full_dataset_mismatches": primary_full_mismatches,
            "primary_model_split_A_test_accuracy": primary_test_accuracy,
            "note": (
                "primary_model_full_dataset_mismatches confirms, rather than "
                "assumes, that the primary (Split A) model has no genuine "
                "misclassification anywhere in the dataset to use as the "
                "'incorrectly classified' example -- hence the documented "
                "substitution of the secondary (Split B) model for that one "
                "case only."
            ),
        },
    }


# ---------------------------------------------------------------------------
# B. Local explanation generation
# ---------------------------------------------------------------------------

RAW_FEATURE_COLUMNS = [
    "resource_type", "changed_attribute", "security_sensitivity",
    "public_exposure", "encryption_change", "privilege_change",
    "port_exposure", "change_magnitude", "drift_frequency",
]


def explain_single_record(row_index, df, X, y_encoded, model, preprocessor, inverse_mapping, top_n=5):
    """
    Produces one local explanation dict for a single record, using ONLY
    values actually computed by SHAP -- no manually written narrative.
    """
    row_X = X.loc[[row_index]]
    true_label_int = int(y_encoded[df.index.get_loc(row_index)])
    true_label = inverse_mapping[true_label_int]

    X_transformed, feature_names = transform_with_saved_preprocessor(preprocessor, row_X)

    predicted_probs = model.predict_proba(X_transformed)[0]
    predicted_class_int = int(np.argmax(predicted_probs))
    predicted_label = inverse_mapping[predicted_class_int]

    explainer = build_explainer(model)
    shap_values, base_values = compute_shap_values(explainer, X_transformed)  # (1, n_features, n_classes)

    additivity = check_additivity(shap_values, base_values, model, X_transformed)

    # Requirement: SHAP values must correspond to the PREDICTED class.
    predicted_class_shap = shap_values[0, :, predicted_class_int]

    ranked = sorted(zip(feature_names, predicted_class_shap.tolist()), key=lambda p: -p[1])
    top_positive = [{"feature": f, "shap_value": v} for f, v in ranked[:top_n] if v > 0]
    top_negative = [{"feature": f, "shap_value": v} for f, v in ranked[::-1][:top_n] if v < 0]

    full_shap_for_predicted_class = [
        {"feature": f, "shap_value": v} for f, v in zip(feature_names, predicted_class_shap.tolist())
    ]

    original_feature_values = {col: _json_safe(df.loc[row_index, col]) for col in RAW_FEATURE_COLUMNS}

    return {
        "row_index": int(row_index),
        "scenario_id": df.loc[row_index, "scenario_id"],
        "actual_label": true_label,
        "predicted_label": predicted_label,
        "prediction_correct": true_label == predicted_label,
        "prediction_probabilities": {inverse_mapping[i]: float(p) for i, p in enumerate(predicted_probs)},
        "shap_values_correspond_to_class": predicted_label,
        "additivity_check": additivity,
        "top_positive_contributors": top_positive,
        "top_negative_contributors": top_negative,
        "all_shap_values_for_predicted_class": full_shap_for_predicted_class,
        "original_feature_values": original_feature_values,
    }


def _json_safe(value):
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def plot_local_waterfall(row_index, df, X, y_encoded, model, preprocessor, inverse_mapping, title, out_path):
    """Per-record waterfall plot for the record's PREDICTED class, built
    from the actual SHAP Explanation object (not a hand-drawn chart)."""
    row_X = X.loc[[row_index]]
    X_transformed, feature_names = transform_with_saved_preprocessor(preprocessor, row_X)
    predicted_probs = model.predict_proba(X_transformed)[0]
    predicted_class_int = int(np.argmax(predicted_probs))

    explainer = build_explainer(model)
    shap_values, base_values = compute_shap_values(explainer, X_transformed)

    explanation = shap.Explanation(
        values=shap_values[0, :, predicted_class_int],
        base_values=base_values[predicted_class_int],
        data=X_transformed[0],
        feature_names=feature_names,
    )
    fig = plt.figure()
    shap.plots.waterfall(explanation, show=False, max_display=12)
    plt.title(f"{title}\nPredicted: {inverse_mapping[predicted_class_int]}", fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_shap_milestone():
    os.makedirs(SHAP_DIR, exist_ok=True)

    artifacts = load_models_and_preprocessors()
    df, X, y, y_encoded, metadata = load_full_dataset_prepared()
    inverse_mapping = artifacts["int_to_label"]

    rf_primary = artifacts["random_forest_primary"]
    dt_primary = artifacts["decision_tree_primary"]
    preprocessor_primary = artifacts["preprocessor_primary"]

    # --- Preprocessing + feature-name alignment (requirements 5-6) ---
    X_transformed, feature_names = transform_with_saved_preprocessor(preprocessor_primary, X)
    alignment = verify_feature_name_alignment(X_transformed, feature_names)
    assert alignment["aligned"], "Transformed feature count does not match feature name count"

    # --- Explainer verification for BOTH saved models (requirement 2, 4) ---
    rf_explainer = build_explainer(rf_primary)
    dt_explainer = build_explainer(dt_primary)
    rf_shap_values, rf_base_values = compute_shap_values(rf_explainer, X_transformed)
    dt_shap_values, dt_base_values = compute_shap_values(dt_explainer, X_transformed)

    rf_additivity = check_additivity(rf_shap_values, rf_base_values, rf_primary, X_transformed)
    dt_additivity = check_additivity(dt_shap_values, dt_base_values, dt_primary, X_transformed)

    # --- A. Global explanations (Random Forest, primary model) ---
    global_importance = compute_global_feature_importance(rf_shap_values, feature_names, inverse_mapping)

    critical_class_index = artifacts["label_to_int"]["Critical"]
    plot_global_beeswarm(
        rf_shap_values, rf_base_values, X_transformed, feature_names,
        critical_class_index, "Critical", os.path.join(SHAP_DIR, "global_summary.png"),
    )
    plot_global_bar(
        rf_shap_values, X_transformed, feature_names, RISK_LABEL_ORDER,
        os.path.join(SHAP_DIR, "global_bar.png"),
    )

    with open(os.path.join(SHAP_DIR, "global_feature_importance.json"), "w") as f:
        json.dump(
            {
                "model": "random_forest_primary",
                "shap_explainer": "TreeExplainer",
                "shap_version": SHAP_VERSION,
                "n_samples_used": int(X_transformed.shape[0]),
                "feature_name_alignment": alignment,
                "additivity_check": rf_additivity,
                **global_importance,
            },
            f,
            indent=2,
        )

    # --- B. Local explanations ---
    selections = select_representative_records(df, artifacts)

    local_specs = [
        ("critical_security_group_public_exposure", "local_critical.png", "Critical: Security-Group Public Exposure"),
        ("high_iam_privilege_change", "local_iam_high.png", "High: IAM Privilege Change"),
        ("medium_e7_case", "local_e7_medium.png", "Medium: E7 (Peer Security-Group Reference)"),
        ("low_e5_no_drift_control", "local_e5_low.png", "Low: E5 Non-Drift Control"),
        ("correctly_classified", "local_correct.png", "Correctly Classified Example (Primary Model, Split A Test Set)"),
        ("incorrectly_classified", "local_incorrect.png", "Incorrectly Classified Example (Secondary Model, Split B)"),
    ]

    local_explanations = {"selection_diagnostics": selections["diagnostics"]}

    for key, filename, title in local_specs:
        sel = selections[key]
        row_idx = sel["row_index"]
        if sel["model"] == "primary":
            model_used, preprocessor_used = rf_primary, preprocessor_primary
            model_label = "random_forest_primary"
        else:
            model_used, preprocessor_used = artifacts["random_forest_secondary"], artifacts["preprocessor_secondary"]
            model_label = "random_forest_secondary_scenario_split"

        explanation = explain_single_record(
            row_idx, df, X, y_encoded, model_used, preprocessor_used, inverse_mapping
        )
        explanation["model_used"] = model_label
        explanation["source"] = sel.get("source", "primary_model_full_dataset")
        local_explanations[key] = explanation

        plot_local_waterfall(
            row_idx, df, X, y_encoded, model_used, preprocessor_used, inverse_mapping,
            title, os.path.join(SHAP_DIR, filename),
        )

    with open(os.path.join(SHAP_DIR, "local_explanations.json"), "w") as f:
        json.dump(local_explanations, f, indent=2)

    return {
        "alignment": alignment,
        "rf_additivity": rf_additivity,
        "dt_additivity": dt_additivity,
        "global_importance": global_importance,
        "local_explanations": local_explanations,
        "selections": selections,
    }


def print_summary(results):
    print("=" * 78)
    print("SHAP EXPLAINABILITY MILESTONE SUMMARY")
    print("=" * 78)
    print(f"SHAP version: {SHAP_VERSION}")
    print(f"Feature-name alignment: {results['alignment']}")
    print(f"Random Forest additivity check: {results['rf_additivity']}")
    print(f"Decision Tree additivity check: {results['dt_additivity']}")
    print()
    print("Top 5 features by mean |SHAP| (overall, across all classes):")
    for entry in results["global_importance"]["mean_abs_shap_overall_across_all_classes"][:5]:
        print(f"  {entry['feature']:50s} {entry['mean_abs_shap']:.4f}")
    print()
    print("Local explanation summary:")
    for key, exp in results["local_explanations"].items():
        if key == "selection_diagnostics":
            continue
        print(f"  {key}: row={exp['row_index']} scenario={exp['scenario_id']} "
              f"actual={exp['actual_label']} predicted={exp['predicted_label']} "
              f"correct={exp['prediction_correct']} model={exp['model_used']}")
    print()
    print(f"Selection diagnostics: {results['local_explanations']['selection_diagnostics']}")
    print("=" * 78)


if __name__ == "__main__":
    results = run_shap_milestone()
    print_summary(results)
    print(f"\nArtifacts saved to: {SHAP_DIR}")
