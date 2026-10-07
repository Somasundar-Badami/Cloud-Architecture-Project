"""
ml_pipeline.py

Loads the completed and validated dataset (data/dataset.csv) -- NOT
regenerated or modified here -- and trains/evaluates a Random Forest
(primary) and a Decision Tree (baseline) risk classifier.

Does NOT implement SHAP. That is the next milestone.

Two evaluation strategies are run and reported side by side:
  Split A: stratified random split (record-level)      -- requirement 7
  Split B: scenario-group-aware split (GroupShuffleSplit
           with groups=scenario_id)                      -- requirement 8

Split A is treated as primary (its fitted preprocessor + models are the
ones saved under models/ without a suffix). Split B is a supplementary,
harder evaluation used specifically to investigate scenario leakage; its
artifacts are saved with a "_scenario_split" suffix for inspection.
"""

import os
import json

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder
from sklearn.model_selection import train_test_split, GroupShuffleSplit
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix,
    classification_report,
)

RANDOM_STATE = 42

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: E402

DATA_DIR = project_paths.PROCESSED_DATA_DIR
MODELS_DIR = project_paths.MODELS_DIR
RESULTS_DIR = project_paths.RESULTS_DIR
DATASET_CSV = os.path.join(DATA_DIR, "dataset.csv")

# ---------------------------------------------------------------------------
# Approved feature schema (frozen implementation spec, Section 4)
# ---------------------------------------------------------------------------

METADATA_COLUMNS = ["record_id", "scenario_id", "group_id"]
TARGET_COLUMN = "risk_label"

ORDINAL_FEATURES = {
    # column -> explicit severity order (least -> most severe)
    "security_sensitivity": ["Low", "Medium", "High"],
    "change_magnitude": ["None", "Low", "Medium", "High"],
    "port_exposure": ["none", "internal", "0.0.0.0/0"],
}
NOMINAL_FEATURES = ["resource_type", "changed_attribute"]
BOOLEAN_FEATURES = ["public_exposure", "encryption_change", "privilege_change"]
NUMERIC_FEATURES = ["drift_frequency"]

FEATURE_COLUMNS = (
    list(ORDINAL_FEATURES.keys()) + NOMINAL_FEATURES + BOOLEAN_FEATURES + NUMERIC_FEATURES
)

RISK_LABEL_ORDER = ["Low", "Medium", "High", "Critical"]


# ---------------------------------------------------------------------------
# Loading and splitting
# ---------------------------------------------------------------------------

def load_dataset(csv_path=DATASET_CSV):
    """
    Load data/dataset.csv.

    IMPORTANT DATA-LOADING DETAIL (not a dataset bug -- verified by
    inspecting the raw CSV bytes): change_magnitude legitimately contains
    the literal string "None" for the E5 non-drift control scenario
    (meaning "no drift occurred, so there is no magnitude to measure").
    pandas' default read_csv NA-value list includes the bare word "None",
    which would silently turn every one of those 90 control records into
    a missing value. keep_default_na=False (with an explicit empty-string
    NA marker) preserves "None" as a real category instead.
    """
    df = pd.read_csv(csv_path, keep_default_na=False, na_values=[""])
    return df


def separate_features_target_metadata(df: pd.DataFrame):
    """
    Splits the loaded DataFrame into (X, y, metadata).

    EXCLUDED from X, with justification:
      - record_id: unique per row; including it would let a model key off
        row identity instead of learning from attributes.
      - desired_state / actual_state / old_value / new_value: not present
        in dataset.csv at all (they live only in raw_records.json). Even
        if present, the frozen spec explicitly excludes raw config values
        from the ML feature set (see feature_extraction.py docstring).
      - scenario_id / group_id: EXCLUDED, justified as follows -- every
        record's risk_label is a fixed, deterministic property of its
        scenario_id (see scenario_definitions.py -> SCENARIO_REGISTRY).
        Feeding scenario_id (or group_id, which is prefixed by
        scenario_id) into the model would let it memorize a
        scenario_id -> risk_label lookup table instead of learning from
        the actual security-relevant attributes. A real AWS resource has
        no "scenario_id" field -- it is purely an artifact of how this
        synthetic dataset was constructed. A model trained on it would
        look perfect here and generalize to nothing in production.
    """
    metadata = df[METADATA_COLUMNS].copy()
    y = df[TARGET_COLUMN].copy()
    X = df[FEATURE_COLUMNS].copy()
    # Boolean columns arrive from pandas as real bool dtype; cast to int
    # explicitly so every downstream consumer sees a plain numeric array.
    X[BOOLEAN_FEATURES] = X[BOOLEAN_FEATURES].astype(int)
    return X, y, metadata


def encode_target(y: pd.Series):
    """
    Fixed severity-ordered integer mapping (Low=0 ... Critical=3), NOT
    sklearn's LabelEncoder default (which sorts alphabetically and would
    give Critical=0, obscuring the natural severity order in reports).
    Saved as a plain dict for full transparency/auditability.
    """
    mapping = {label: i for i, label in enumerate(RISK_LABEL_ORDER)}
    inverse_mapping = {i: label for label, i in mapping.items()}
    y_encoded = y.map(mapping).values
    if np.any(pd.isnull(y_encoded)):
        unmapped = sorted(set(y[y.map(mapping).isnull()]))
        raise ValueError(f"Unmapped risk_label values found: {unmapped}")
    return y_encoded, mapping, inverse_mapping


def build_preprocessor():
    """
    ColumnTransformer:
      - OrdinalEncoder (explicit severity order) for security_sensitivity,
        change_magnitude, port_exposure
      - OneHotEncoder(handle_unknown="ignore") for resource_type,
        changed_attribute. handle_unknown="ignore" is REQUIRED for the
        scenario-group-aware split: an entire scenario_id (and therefore
        its unique changed_attribute string, e.g. "block_public_access")
        can be held out of training entirely, so transform() must be able
        to handle a category it never saw during fit rather than raising.
      - Boolean/numeric columns passed through unchanged
    """
    ordinal_cols = list(ORDINAL_FEATURES.keys())
    ordinal_categories = list(ORDINAL_FEATURES.values())

    preprocessor = ColumnTransformer(
        transformers=[
            ("ordinal", OrdinalEncoder(categories=ordinal_categories), ordinal_cols),
            ("nominal", OneHotEncoder(handle_unknown="ignore"), NOMINAL_FEATURES),
            ("passthrough", "passthrough", BOOLEAN_FEATURES + NUMERIC_FEATURES),
        ],
        remainder="drop",
    )
    return preprocessor


def stratified_random_split(X, y_encoded, test_size=0.2, random_state=RANDOM_STATE):
    """
    Requirement 7: reproducible stratified train/test split (record-level),
    stratified on the encoded target label.
    """
    indices = np.arange(len(X))
    train_idx, test_idx = train_test_split(
        indices, test_size=test_size, random_state=random_state, stratify=y_encoded
    )
    return train_idx, test_idx


def scenario_group_split(X, y_encoded, metadata, test_size=0.2, random_state=RANDOM_STATE):
    """
    Requirement 8: scenario-group-aware split. GroupShuffleSplit with
    groups=scenario_id guarantees every record of a given scenario_id ends
    up entirely on one side -- never split across train and test. This
    evaluates generalization to entire unseen drift *patterns*, not just
    unseen drift_frequency draws of an already-seen pattern.
    """
    groups = metadata["scenario_id"].values
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(splitter.split(X, y_encoded, groups=groups))
    return train_idx, test_idx


def describe_split_leakage(metadata: pd.DataFrame, train_idx, test_idx):
    """
    Empirically checks (rather than just asserting) whether any
    scenario_id or group_id appears on BOTH sides of a given split.
    """
    train_scenarios = set(metadata.iloc[train_idx]["scenario_id"])
    test_scenarios = set(metadata.iloc[test_idx]["scenario_id"])
    train_groups = set(metadata.iloc[train_idx]["group_id"])
    test_groups = set(metadata.iloc[test_idx]["group_id"])

    scenario_overlap = sorted(train_scenarios & test_scenarios)
    group_overlap = sorted(train_groups & test_groups)

    return {
        "num_scenarios_in_train": len(train_scenarios),
        "num_scenarios_in_test": len(test_scenarios),
        "scenario_ids_appearing_in_both_train_and_test": scenario_overlap,
        "num_scenarios_leaked": len(scenario_overlap),
        "num_group_ids_appearing_in_both_train_and_test": len(group_overlap),
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_random_forest(X_train, y_train, random_state=RANDOM_STATE):
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    return model


def train_decision_tree(X_train, y_train, random_state=RANDOM_STATE):
    model = DecisionTreeClassifier(random_state=random_state)
    model.fit(X_train, y_train)
    return model


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_model(model, X_test, y_test, inverse_mapping):
    y_pred = model.predict(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    precision_macro, recall_macro, f1_macro, _ = precision_recall_fscore_support(
        y_test, y_pred, average="macro", zero_division=0
    )
    precision_weighted, recall_weighted, f1_weighted, _ = precision_recall_fscore_support(
        y_test, y_pred, average="weighted", zero_division=0
    )

    labels_sorted = sorted(inverse_mapping.keys())
    label_names = [inverse_mapping[i] for i in labels_sorted]

    cm = confusion_matrix(y_test, y_pred, labels=labels_sorted)
    report_dict = classification_report(
        y_test,
        y_pred,
        labels=labels_sorted,
        target_names=label_names,
        output_dict=True,
        zero_division=0,
    )

    return {
        "n_test_samples": int(len(y_test)),
        "accuracy": float(accuracy),
        "precision_macro": float(precision_macro),
        "recall_macro": float(recall_macro),
        "f1_macro": float(f1_macro),
        "precision_weighted": float(precision_weighted),
        "recall_weighted": float(recall_weighted),
        "f1_weighted": float(f1_weighted),
        "confusion_matrix": cm.tolist(),
        "confusion_matrix_labels": label_names,
        "classification_report": report_dict,
    }


def get_feature_importance(model, feature_names):
    importances = model.feature_importances_
    pairs = sorted(zip(feature_names, importances), key=lambda pair: -pair[1])
    return [{"feature": f, "importance": float(v)} for f, v in pairs]


# ---------------------------------------------------------------------------
# End-to-end orchestration for one split strategy
# ---------------------------------------------------------------------------

def run_split(X, y_encoded, metadata, train_idx, test_idx, split_name):
    preprocessor = build_preprocessor()
    X_train_raw, X_test_raw = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y_encoded[train_idx], y_encoded[test_idx]

    X_train = preprocessor.fit_transform(X_train_raw)
    X_test = preprocessor.transform(X_test_raw)
    feature_names = list(preprocessor.get_feature_names_out())

    rf_model = train_random_forest(X_train, y_train)
    dt_model = train_decision_tree(X_train, y_train)

    inverse_mapping = {i: label for i, label in enumerate(RISK_LABEL_ORDER)}

    rf_metrics = evaluate_model(rf_model, X_test, y_test, inverse_mapping)
    dt_metrics = evaluate_model(dt_model, X_test, y_test, inverse_mapping)

    rf_importance = get_feature_importance(rf_model, feature_names)
    dt_importance = get_feature_importance(dt_model, feature_names)

    leakage_report = describe_split_leakage(metadata, train_idx, test_idx)

    return {
        "split_name": split_name,
        "leakage_report": leakage_report,
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "preprocessor": preprocessor,
        "feature_names": feature_names,
        "random_forest": {"model": rf_model, "metrics": rf_metrics, "feature_importance": rf_importance},
        "decision_tree": {"model": dt_model, "metrics": dt_metrics, "feature_importance": dt_importance},
    }


# ---------------------------------------------------------------------------
# Saving artifacts
# ---------------------------------------------------------------------------

def save_artifacts(split_a_result, split_b_result, label_mapping, inverse_mapping):
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # --- Primary artifacts (Split A: stratified random split) ---
    joblib.dump(split_a_result["random_forest"]["model"], os.path.join(MODELS_DIR, "random_forest_model.joblib"))
    joblib.dump(split_a_result["decision_tree"]["model"], os.path.join(MODELS_DIR, "decision_tree_model.joblib"))
    joblib.dump(split_a_result["preprocessor"], os.path.join(MODELS_DIR, "preprocessor.joblib"))
    with open(os.path.join(MODELS_DIR, "label_mapping.json"), "w") as f:
        json.dump({"label_to_int": label_mapping, "int_to_label": inverse_mapping}, f, indent=2)

    # --- Secondary artifacts (Split B: scenario-group-aware split) ---
    joblib.dump(split_b_result["random_forest"]["model"], os.path.join(MODELS_DIR, "random_forest_model_scenario_split.joblib"))
    joblib.dump(split_b_result["decision_tree"]["model"], os.path.join(MODELS_DIR, "decision_tree_model_scenario_split.joblib"))
    joblib.dump(split_b_result["preprocessor"], os.path.join(MODELS_DIR, "preprocessor_scenario_split.joblib"))

    # --- Metrics (both splits) ---
    def _strip_models(split_result):
        return {
            "split_name": split_result["split_name"],
            "leakage_report": split_result["leakage_report"],
            "n_train": split_result["n_train"],
            "n_test": split_result["n_test"],
            "random_forest": split_result["random_forest"]["metrics"],
            "decision_tree": split_result["decision_tree"]["metrics"],
        }

    metrics_report = {
        "split_A_stratified_random": _strip_models(split_a_result),
        "split_B_scenario_group_aware": _strip_models(split_b_result),
    }
    with open(os.path.join(RESULTS_DIR, "metrics.json"), "w") as f:
        json.dump(metrics_report, f, indent=2)

    # --- Confusion matrices (standalone file for convenience) ---
    confusion_matrices = {
        "split_A_stratified_random": {
            "random_forest": split_a_result["random_forest"]["metrics"]["confusion_matrix"],
            "decision_tree": split_a_result["decision_tree"]["metrics"]["confusion_matrix"],
            "labels": split_a_result["random_forest"]["metrics"]["confusion_matrix_labels"],
        },
        "split_B_scenario_group_aware": {
            "random_forest": split_b_result["random_forest"]["metrics"]["confusion_matrix"],
            "decision_tree": split_b_result["decision_tree"]["metrics"]["confusion_matrix"],
            "labels": split_b_result["random_forest"]["metrics"]["confusion_matrix_labels"],
        },
    }
    with open(os.path.join(RESULTS_DIR, "confusion_matrices.json"), "w") as f:
        json.dump(confusion_matrices, f, indent=2)

    # --- Feature importance ---
    feature_importance_report = {
        "split_A_random_forest": split_a_result["random_forest"]["feature_importance"],
        "split_A_decision_tree": split_a_result["decision_tree"]["feature_importance"],
        "split_B_random_forest": split_b_result["random_forest"]["feature_importance"],
        "split_B_decision_tree": split_b_result["decision_tree"]["feature_importance"],
    }
    with open(os.path.join(RESULTS_DIR, "feature_importance.json"), "w") as f:
        json.dump(feature_importance_report, f, indent=2)

    return metrics_report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_training_pipeline():
    df = load_dataset()
    X, y, metadata = separate_features_target_metadata(df)
    y_encoded, label_mapping, inverse_mapping = encode_target(y)

    # Split A: stratified random (record-level)
    train_idx_a, test_idx_a = stratified_random_split(X, y_encoded)
    split_a_result = run_split(X, y_encoded, metadata, train_idx_a, test_idx_a, "split_A_stratified_random")

    # Split B: scenario-group-aware
    train_idx_b, test_idx_b = scenario_group_split(X, y_encoded, metadata)
    split_b_result = run_split(X, y_encoded, metadata, train_idx_b, test_idx_b, "split_B_scenario_group_aware")

    metrics_report = save_artifacts(split_a_result, split_b_result, label_mapping, inverse_mapping)

    return {
        "split_a_result": split_a_result,
        "split_b_result": split_b_result,
        "metrics_report": metrics_report,
    }


def print_summary(results):
    for key, split_result in [
        ("SPLIT A -- Stratified Random Split (record-level)", results["split_a_result"]),
        ("SPLIT B -- Scenario-Group-Aware Split (GroupShuffleSplit by scenario_id)", results["split_b_result"]),
    ]:
        print("=" * 78)
        print(key)
        print("=" * 78)
        leak = split_result["leakage_report"]
        print(f"Train records: {split_result['n_train']}  |  Test records: {split_result['n_test']}")
        print(f"Scenarios in train: {leak['num_scenarios_in_train']}  |  Scenarios in test: {leak['num_scenarios_in_test']}")
        print(f"Scenario IDs appearing in BOTH train and test: {leak['scenario_ids_appearing_in_both_train_and_test']} "
              f"({leak['num_scenarios_leaked']} scenarios leaked)")
        print()
        for model_name in ["random_forest", "decision_tree"]:
            m = split_result[model_name]["metrics"]
            print(f"--- {model_name.replace('_', ' ').title()} ---")
            print(f"  Accuracy:            {m['accuracy']:.4f}")
            print(f"  Precision (macro):   {m['precision_macro']:.4f}")
            print(f"  Recall (macro):      {m['recall_macro']:.4f}")
            print(f"  F1 (macro):          {m['f1_macro']:.4f}")
            print(f"  Precision (weighted):{m['precision_weighted']:.4f}")
            print(f"  Recall (weighted):   {m['recall_weighted']:.4f}")
            print(f"  F1 (weighted):       {m['f1_weighted']:.4f}")
            print(f"  Confusion matrix (rows=true, cols=pred, labels={m['confusion_matrix_labels']}):")
            for row in m["confusion_matrix"]:
                print(f"    {row}")
            print()
        print()


if __name__ == "__main__":
    results = run_training_pipeline()
    print_summary(results)
    print(f"Artifacts saved to: {MODELS_DIR}")
    print(f"Results saved to:   {RESULTS_DIR}")
