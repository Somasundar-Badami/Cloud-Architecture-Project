"""
portable_model.py

Pure-Python (standard library only) re-implementation of the PRIMARY
trained pipeline -- fitted ColumnTransformer + RandomForestClassifier --
plus exact path-dependent TreeSHAP, loaded from a JSON export of the
already-trained artifacts.

Why this exists:
    scikit-learn + scipy + numpy + shap together exceed AWS Lambda's
    250 MB deployment-package limit, and a SageMaker real-time endpoint
    bills per hour even when idle. The trained forest itself is tiny
    (200 trees, ~5.5k nodes), so for the AWS deployment the model is
    exported ONCE to models/portable_model.json and evaluated here with
    no third-party dependencies.

    Nothing is retrained. export_portable_model() only reads the fitted
    tree arrays and encoder categories from the saved joblib artifacts.
    tests/test_portable_model.py checks that predict_proba() and
    shap_values() here match sklearn and shap.TreeExplainer numerically
    on real dataset records.

TreeSHAP:
    Algorithm 2 of Lundberg et al., "Consistent Individualized Feature
    Attribution for Tree Ensembles" (2018) -- the same path-dependent
    algorithm shap.TreeExplainer(model) uses when no background dataset
    is given, with node covers taken from weighted_n_node_samples.
"""

import hashlib
import json
import os
from typing import Any, Dict, List

FORMAT_VERSION = 1


# ---------------------------------------------------------------------------
# Export (runs locally, needs sklearn/joblib -- imported lazily so that the
# Lambda runtime, which never calls this, does not need them)
# ---------------------------------------------------------------------------

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def export_portable_model(model_path: str, preprocessor_path: str, label_mapping_path: str) -> Dict[str, Any]:
    import joblib
    import sklearn
    from ml_pipeline import FEATURE_COLUMNS, BOOLEAN_FEATURES

    model = joblib.load(model_path)
    preprocessor = joblib.load(preprocessor_path)
    with open(label_mapping_path) as f:
        int_to_label = {int(k): v for k, v in json.load(f)["int_to_label"].items()}

    steps: List[Dict[str, Any]] = []
    transformed_names: List[str] = []
    for name, transformer, columns in preprocessor.transformers_:
        if name == "remainder":
            continue
        kind = type(transformer).__name__
        if kind == "OrdinalEncoder":
            for col, cats in zip(columns, transformer.categories_):
                steps.append({"type": "ordinal", "column": col, "categories": [str(c) for c in cats]})
                transformed_names.append(f"{name}__{col}")
        elif kind == "OneHotEncoder":
            if transformer.handle_unknown != "ignore":
                raise ValueError("portable_model only supports OneHotEncoder(handle_unknown='ignore')")
            for col, cats in zip(columns, transformer.categories_):
                steps.append({"type": "onehot", "column": col, "categories": [str(c) for c in cats]})
                transformed_names.extend(f"{name}__{col}_{c}" for c in cats)
        elif kind == "FunctionTransformer" or transformer == "passthrough":
            for col in columns:
                steps.append({"type": "passthrough", "column": col})
                transformed_names.append(f"{name}__{col}")
        else:
            raise ValueError(f"Unsupported transformer in preprocessor: {name} ({kind})")

    expected_names = list(preprocessor.get_feature_names_out())
    if transformed_names != expected_names:
        raise ValueError("Exported feature order does not match preprocessor.get_feature_names_out()")

    trees = []
    for estimator in model.estimators_:
        t = estimator.tree_
        values = []
        for row in t.value[:, 0, :]:
            total = float(row.sum())
            values.append([float(v) / total for v in row])
        trees.append({
            "children_left": [int(v) for v in t.children_left],
            "children_right": [int(v) for v in t.children_right],
            "feature": [int(v) for v in t.feature],
            "threshold": [float(v) for v in t.threshold],
            "value": values,
            "cover": [float(v) for v in t.weighted_n_node_samples],
        })

    return {
        "format_version": FORMAT_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "boolean_features": list(BOOLEAN_FEATURES),
        "preprocessing": steps,
        "transformed_feature_names": transformed_names,
        "classes": [int_to_label[int(c)] for c in model.classes_],
        "trees": trees,
        "source": {
            "model_file": os.path.basename(model_path),
            "model_sha256": _sha256(model_path),
            "preprocessor_file": os.path.basename(preprocessor_path),
            "preprocessor_sha256": _sha256(preprocessor_path),
            "sklearn_version": sklearn.__version__,
        },
    }


# ---------------------------------------------------------------------------
# TreeSHAP (Algorithm 2). A path element is [feature, zero_fraction,
# one_fraction, weight]; the first element of every path is a dummy (-1).
# ---------------------------------------------------------------------------

def _extend(path, zero_fraction, one_fraction, feature):
    depth = len(path)
    path = [list(e) for e in path]
    path.append([feature, zero_fraction, one_fraction, 1.0 if depth == 0 else 0.0])
    for i in range(depth - 1, -1, -1):
        path[i + 1][3] += one_fraction * path[i][3] * (i + 1) / (depth + 1)
        path[i][3] = zero_fraction * path[i][3] * (depth - i) / (depth + 1)
    return path


def _unwind(path, index):
    depth = len(path) - 1
    path = [list(e) for e in path]
    one_fraction = path[index][2]
    zero_fraction = path[index][1]
    next_one_portion = path[depth][3]
    for j in range(depth - 1, -1, -1):
        if one_fraction != 0:
            tmp = path[j][3]
            path[j][3] = next_one_portion * (depth + 1) / ((j + 1) * one_fraction)
            next_one_portion = tmp - path[j][3] * zero_fraction * (depth - j) / (depth + 1)
        else:
            path[j][3] = path[j][3] * (depth + 1) / (zero_fraction * (depth - j))
    for j in range(index, depth):
        path[j][0], path[j][1], path[j][2] = path[j + 1][0], path[j + 1][1], path[j + 1][2]
    return path[:depth]


def _tree_shap(tree, x, phi):
    left, right = tree["children_left"], tree["children_right"]
    feature, threshold = tree["feature"], tree["threshold"]
    value, cover = tree["value"], tree["cover"]
    n_classes = len(value[0])

    def recurse(node, path, zero_fraction, one_fraction, feature_index):
        path = _extend(path, zero_fraction, one_fraction, feature_index)
        if left[node] == -1:
            leaf_value = value[node]
            for i in range(1, len(path)):
                weight = sum(e[3] for e in _unwind(path, i))
                scale = weight * (path[i][2] - path[i][1])
                row = phi[path[i][0]]
                for c in range(n_classes):
                    row[c] += scale * leaf_value[c]
            return
        f = feature[node]
        hot, cold = (left[node], right[node]) if x[f] <= threshold[node] else (right[node], left[node])
        incoming_zero, incoming_one = 1.0, 1.0
        for k in range(1, len(path)):
            if path[k][0] == f:
                incoming_zero, incoming_one = path[k][1], path[k][2]
                path = _unwind(path, k)
                break
        recurse(hot, path, incoming_zero * cover[hot] / cover[node], incoming_one, f)
        recurse(cold, path, incoming_zero * cover[cold] / cover[node], 0.0, f)

    recurse(0, [], 1.0, 1.0, -1)


def _leaf_value(tree, x):
    node = 0
    left, right = tree["children_left"], tree["children_right"]
    while left[node] != -1:
        node = left[node] if x[tree["feature"][node]] <= tree["threshold"][node] else right[node]
    return tree["value"][node]


# ---------------------------------------------------------------------------
# Runtime model
# ---------------------------------------------------------------------------

class PortableRiskModel:
    def __init__(self, exported: Dict[str, Any]):
        if exported.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"Unsupported portable model format: {exported.get('format_version')}")
        self.feature_columns = exported["feature_columns"]
        self.boolean_features = set(exported["boolean_features"])
        self.steps = exported["preprocessing"]
        self.feature_names = exported["transformed_feature_names"]
        self.classes = exported["classes"]
        self.trees = exported["trees"]
        self.source = exported.get("source", {})

    @classmethod
    def load(cls, path: str) -> "PortableRiskModel":
        with open(path) as f:
            return cls(json.load(f))

    def transform(self, features: Dict[str, Any]) -> List[float]:
        """Same output as the fitted ColumnTransformer for one feature dict
        (as returned by feature_extraction.extract_features)."""
        x: List[float] = []
        for step in self.steps:
            raw = features[step["column"]]
            if step["type"] == "ordinal":
                if str(raw) not in step["categories"]:
                    # sklearn's OrdinalEncoder (no handle_unknown) raises too
                    raise ValueError(f"Unknown category {raw!r} for ordinal feature '{step['column']}'")
                x.append(float(step["categories"].index(str(raw))))
            elif step["type"] == "onehot":
                x.extend(1.0 if str(raw) == c else 0.0 for c in step["categories"])
            else:
                x.append(float(int(raw)) if step["column"] in self.boolean_features else float(raw))
        return x

    def predict_proba(self, x: List[float]) -> List[float]:
        totals = [0.0] * len(self.classes)
        for tree in self.trees:
            for c, v in enumerate(_leaf_value(tree, x)):
                totals[c] += v
        return [t / len(self.trees) for t in totals]

    def expected_value(self) -> List[float]:
        totals = [0.0] * len(self.classes)
        for tree in self.trees:
            for c, v in enumerate(tree["value"][0]):
                totals[c] += v
        return [t / len(self.trees) for t in totals]

    def shap_values(self, x: List[float]) -> List[List[float]]:
        """Returns phi[feature][class], averaged over trees."""
        phi = [[0.0] * len(self.classes) for _ in self.feature_names]
        for tree in self.trees:
            _tree_shap(tree, x, phi)
        n = len(self.trees)
        return [[v / n for v in row] for row in phi]

    def explain(self, features: Dict[str, Any], top_k: int = 5) -> Dict[str, Any]:
        """Prediction + SHAP explanation for the predicted class."""
        x = self.transform(features)
        proba = self.predict_proba(x)
        predicted = max(range(len(proba)), key=lambda i: proba[i])
        phi = self.shap_values(x)
        base = self.expected_value()
        contributions = {name: phi[i][predicted] for i, name in enumerate(self.feature_names)}
        ranked = sorted(contributions.items(), key=lambda kv: -kv[1])
        return {
            "predicted_label": self.classes[predicted],
            "probabilities": {label: proba[i] for i, label in enumerate(self.classes)},
            "base_value": base[predicted],
            "shap_values": contributions,
            "top_positive_contributors": [[k, v] for k, v in ranked if v > 0][:top_k],
            "top_negative_contributors": [[k, v] for k, v in reversed(ranked) if v < 0][:top_k],
            "additivity_error": abs(base[predicted] + sum(contributions.values()) - proba[predicted]),
        }


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(here, "..", "models")
    exported = export_portable_model(
        os.path.join(models_dir, "random_forest_model.joblib"),
        os.path.join(models_dir, "preprocessor.joblib"),
        os.path.join(models_dir, "label_mapping.json"),
    )
    out_path = os.path.join(models_dir, "portable_model.json")
    with open(out_path, "w") as f:
        json.dump(exported, f, separators=(",", ":"))
    print(f"Wrote {out_path} ({os.path.getsize(out_path)} bytes, {len(exported['trees'])} trees)")
