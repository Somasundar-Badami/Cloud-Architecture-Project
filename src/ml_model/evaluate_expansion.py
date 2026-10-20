"""
evaluate_expansion.py -- compares the approved 711-record dataset with the
expanded dataset_v2 using the SAME pipeline code (ml_pipeline.py) and splits.
Writes nothing to models/ or results/.

    python src/ml_model/evaluate_expansion.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: F401,E402
import ml_pipeline as mp  # noqa: E402
import validate_dataset as vd  # noqa: E402
import csv  # noqa: E402

ROOT = project_paths.ROOT_DIR
SETS = {
    "approved_711": os.path.join(ROOT, "dataset", "processed", "dataset.csv"),
    "expanded": os.path.join(ROOT, "dataset_v2", "processed", "dataset.csv"),
}


def run(path):
    df = mp.load_dataset(path)
    X, y, meta = mp.separate_features_target_metadata(df)
    y_enc, _, inv = mp.encode_target(y)
    out = {"n_records": int(len(df)), "n_scenarios": int(meta["scenario_id"].nunique())}
    for name, splitter in (("split_A_random", lambda: mp.stratified_random_split(X, y_enc)),
                           ("split_B_unseen_scenarios", lambda: mp.scenario_group_split(X, y_enc, meta))):
        tr, te = splitter()
        r = mp.run_split(X, y_enc, meta, tr, te, name)
        out[name] = {"n_train": r["n_train"], "n_test": r["n_test"]}
        for m in ("random_forest", "decision_tree"):
            mt = r[m]["metrics"]
            out[name][m] = {"accuracy": round(mt["accuracy"], 3), "f1_macro": round(mt["f1_macro"], 3)}
    return out


def rule_check(path):
    import risk_rule_check as rc
    bad = {}
    n = 0
    for row in csv.DictReader(open(path)):
        n += 1
        f = {"public_exposure": row["public_exposure"] == "True",
             "security_sensitivity": row["security_sensitivity"],
             "privilege_change": row["privilege_change"] == "True",
             "encryption_change": row["encryption_change"] == "True",
             "change_magnitude": row["change_magnitude"]}
        if rc.rule_based_label(f) != row["risk_label"]:
            bad[row["scenario_id"]] = bad.get(row["scenario_id"], 0) + 1
    return {"records": n, "rule_mismatches_by_scenario": bad}


if __name__ == "__main__":
    res = {k: run(p) for k, p in SETS.items()}
    res["expanded"]["rule_check"] = rule_check(SETS["expanded"])
    res["approved_711"]["rule_check"] = rule_check(SETS["approved_711"])
    print(json.dumps(res, indent=2))


def repeated_split_b(path, seeds=range(10)):
    """Split B repeated with 10 different random choices of held-out scenarios."""
    import numpy as np
    from sklearn.model_selection import GroupShuffleSplit
    df = mp.load_dataset(path)
    X, y, meta = mp.separate_features_target_metadata(df)
    y_enc, _, inv = mp.encode_target(y)
    scores = {"random_forest": [], "decision_tree": []}
    for s in seeds:
        tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=s)
                      .split(X, y_enc, groups=meta["scenario_id"].values))
        r = mp.run_split(X, y_enc, meta, tr, te, f"B{s}")
        for m in scores:
            scores[m].append(r[m]["metrics"]["accuracy"])
    return {m: {"mean": round(float(np.mean(v)), 3), "min": round(float(np.min(v)), 3),
                "max": round(float(np.max(v)), 3)} for m, v in scores.items()}


if __name__ == "__main__":
    print("\nSplit B repeated over 10 different held-out scenario sets (accuracy):")
    for k, p in SETS.items():
        print(k, json.dumps(repeated_split_b(p)))
