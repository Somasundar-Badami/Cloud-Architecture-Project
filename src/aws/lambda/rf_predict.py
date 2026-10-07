"""
rf_predict.py

Pure-Python inference for the Random Forest exported by
src/ml_model/export_model.py. No numpy / scikit-learn needed, so it runs
inside a plain AWS Lambda zip.

Reproduces sklearn exactly:
  - ColumnTransformer: OrdinalEncoder -> OneHotEncoder(handle_unknown="ignore")
    -> passthrough (bools cast to int)
  - RandomForestClassifier.predict_proba: mean of each tree's leaf class
    distribution; a sample goes left when x[feature] <= threshold.
"""

import json
import os
from typing import Any, Dict, List

_DEFAULT_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "rf_model.json")


class RandomForestJSON:
    def __init__(self, payload: Dict[str, Any]):
        if payload.get("format") != "infradriftguard-rf-v1":
            raise ValueError("Unsupported model format")
        self.classes: List[str] = payload["classes"]
        self.pre = payload["preprocessor"]
        self.trees = payload["trees"]
        self.feature_names: List[str] = self.pre["feature_names"]

    @classmethod
    def load(cls, path: str = _DEFAULT_MODEL_PATH) -> "RandomForestJSON":
        with open(path) as f:
            return cls(json.load(f))

    def transform(self, features: Dict[str, Any]) -> List[float]:
        row: List[float] = []
        for col, cats in self.pre["ordinal"].items():
            value = str(features[col])
            if value not in cats:
                raise ValueError(f"Unknown category {value!r} for ordinal feature {col!r}")
            row.append(float(cats.index(value)))
        for col, cats in self.pre["nominal"].items():
            value = str(features[col])
            row.extend(1.0 if value == c else 0.0 for c in cats)  # unseen -> all zeros
        for col in self.pre["passthrough"]:
            row.append(float(int(features[col])))
        return row

    def _tree_proba(self, tree: Dict[str, Any], x: List[float]) -> List[float]:
        node = 0
        left, right = tree["left"], tree["right"]
        while left[node] != -1:
            node = left[node] if x[tree["feature"][node]] <= tree["threshold"][node] else right[node]
        return tree["value"][node]

    def predict_proba(self, features: Dict[str, Any]) -> Dict[str, float]:
        x = self.transform(features)
        totals = [0.0] * len(self.classes)
        for tree in self.trees:
            for i, p in enumerate(self._tree_proba(tree, x)):
                totals[i] += p
        n = len(self.trees)
        return {label: totals[i] / n for i, label in enumerate(self.classes)}

    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        proba = self.predict_proba(features)
        label = max(self.classes, key=lambda c: proba[c])
        return {"risk_label": label, "confidence": proba[label], "probabilities": proba}
