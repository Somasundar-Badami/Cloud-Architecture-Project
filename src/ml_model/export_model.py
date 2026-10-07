"""
export_model.py

Exports the trained primary Random Forest + its fitted ColumnTransformer
to a single dependency-free JSON file that the AWS Lambda detector loads
with src/aws/lambda/rf_predict.py.

Why: scikit-learn + numpy + scipy + pandas together exceed what fits
comfortably in a Lambda deployment package and would force a container
image or layers. The fitted model is just 200 small decision trees, so
serialising the node arrays (feature, threshold, children, leaf class
distribution) lets the Lambda run the exact same model in pure Python
with zero third-party dependencies -- a ~300 KB zip that cold-starts fast
and stays in the AWS free tier.

Parity with sklearn is verified on all 711 dataset records by
tests/test_export_model.py.

Run:
    python src/ml_model/export_model.py
"""

import os
import sys
import json

import joblib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: E402

from ml_pipeline import ORDINAL_FEATURES, NOMINAL_FEATURES, BOOLEAN_FEATURES, NUMERIC_FEATURES, RISK_LABEL_ORDER  # noqa: E402

DEFAULT_OUTPUT = os.path.join(project_paths.LAMBDA_DIR, "model", "rf_model.json")


def _export_tree(estimator):
    t = estimator.tree_
    leaf_probs = []
    for node_values in t.value:
        dist = [float(v) for v in node_values[0]]
        total = sum(dist)
        leaf_probs.append([round(v / total, 6) if total else 0.0 for v in dist])
    return {
        "left": t.children_left.tolist(),
        "right": t.children_right.tolist(),
        "feature": t.feature.tolist(),
        "threshold": [round(float(x), 6) for x in t.threshold],
        "value": leaf_probs,
    }


def export(model_path=None, preprocessor_path=None, output_path=DEFAULT_OUTPUT):
    model_path = model_path or os.path.join(project_paths.MODELS_DIR, "random_forest_model.joblib")
    preprocessor_path = preprocessor_path or os.path.join(project_paths.MODELS_DIR, "preprocessor.joblib")
    model = joblib.load(model_path)
    preprocessor = joblib.load(preprocessor_path)

    ordinal = preprocessor.named_transformers_["ordinal"]
    nominal = preprocessor.named_transformers_["nominal"]

    payload = {
        "format": "infradriftguard-rf-v1",
        "classes": RISK_LABEL_ORDER,
        "preprocessor": {
            "ordinal": {
                col: [str(c) for c in cats]
                for col, cats in zip(ORDINAL_FEATURES.keys(), ordinal.categories_)
            },
            "nominal": {
                col: [str(c) for c in cats]
                for col, cats in zip(NOMINAL_FEATURES, nominal.categories_)
            },
            "passthrough": BOOLEAN_FEATURES + NUMERIC_FEATURES,
            "feature_names": [str(n) for n in preprocessor.get_feature_names_out()],
        },
        "trees": [_export_tree(est) for est in model.estimators_],
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    return output_path


if __name__ == "__main__":
    path = export()
    print(f"Exported model to {path} ({os.path.getsize(path) / 1024:.1f} KB)")
