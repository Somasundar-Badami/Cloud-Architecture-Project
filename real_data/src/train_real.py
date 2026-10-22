"""
train_real.py -- Step 3: train and evaluate Random Forest on the REAL dataset.

Splits (all "group-aware", so the same group never sits in train and test):
  A  random stratified 5-fold         -> shown only for comparison (leaky)
  B  GroupKFold by repository (5)     -> model has never seen the test repos
  C  GroupKFold by tfsec check (5)    -> model has never seen this KIND of
                                         misconfiguration (hardest, like the
                                         old "unseen scenarios" Split B)
Also trains a second model for the measured label `fixed_later`.

    python train_real.py <dataset_csv> <results_dir>
"""
import json, os, sys
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.metrics import f1_score, accuracy_score, confusion_matrix, roc_auc_score
import shap

FEATURES = ["resource_type", "changed_attribute", "security_sensitivity", "public_exposure",
            "encryption_change", "privilege_change", "port_exposure", "change_magnitude",
            "drift_frequency"]
CLASSES = ["Low", "Medium", "High", "Critical"]
ORD = {"Low": 0, "Medium": 1, "High": 2}
TOP_N = 25


def encode(df):
    X = pd.DataFrame(index=df.index)
    for c in ("resource_type", "changed_attribute"):
        top = df[c].value_counts().index[:TOP_N]
        v = df[c].where(df[c].isin(top), "other")
        X = X.join(pd.get_dummies(v, prefix=c).astype(int))
    X["security_sensitivity"] = df["security_sensitivity"].map(ORD)
    X["change_magnitude"] = df["change_magnitude"].map(ORD)
    for c in ("public_exposure", "encryption_change", "privilege_change"):
        X[c] = df[c].astype(str).eq("True").astype(int)
    X = X.join(pd.get_dummies(df["port_exposure"], prefix="port_exposure").astype(int))
    X["drift_frequency"] = df["drift_frequency"].astype(int)
    return X


def rf():
    return RandomForestClassifier(n_estimators=300, class_weight="balanced",
                                  min_samples_leaf=2, random_state=42, n_jobs=-1)


def cv(X, y, splitter, groups=None):
    pred = np.empty(len(y), dtype=object)
    f1s, dummy = [], []
    for tr, te in splitter.split(X, y, groups):
        m = rf().fit(X.iloc[tr], y[tr])
        pred[te] = m.predict(X.iloc[te])
        f1s.append(f1_score(y[te], pred[te], average="macro", labels=CLASSES, zero_division=0))
        d = DummyClassifier(strategy="stratified", random_state=0).fit(X.iloc[tr], y[tr])
        dummy.append(f1_score(y[te], d.predict(X.iloc[te]), average="macro", labels=CLASSES,
                              zero_division=0))
    return pred, {"macro_f1_mean": round(float(np.mean(f1s)), 3),
                  "macro_f1_min": round(float(np.min(f1s)), 3),
                  "macro_f1_max": round(float(np.max(f1s)), 3),
                  "accuracy_pooled": round(accuracy_score(y, pred), 3),
                  "macro_f1_pooled": round(f1_score(y, pred, average="macro", labels=CLASSES), 3),
                  "random_guess_macro_f1": round(float(np.mean(dummy)), 3)}


def plot_cm(y, pred, title, path):
    cm = confusion_matrix(y, pred, labels=CLASSES)
    fig, ax = plt.subplots(figsize=(5, 4.3))
    ax.imshow(cm, cmap="Blues")
    for i in range(4):
        for j in range(4):
            ax.text(j, i, cm[i, j], ha="center", va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black")
    ax.set_xticks(range(4), CLASSES); ax.set_yticks(range(4), CLASSES)
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual (tfsec severity)"); ax.set_title(title, fontsize=10)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    return cm.tolist()


def main(path, out):
    os.makedirs(out, exist_ok=True)
    df = pd.read_csv(path)
    X, y = encode(df), df["risk_label"].values
    res = {"n_records": len(df), "n_repos": int(df.repo.nunique()), "n_checks": int(df.check.nunique()),
           "label_counts": df.risk_label.value_counts().to_dict()}

    splits = {
        "A_random_5fold": (StratifiedKFold(5, shuffle=True, random_state=42), None),
        "B_unseen_repos": (GroupKFold(5), df["repo"].values),
        "C_unseen_check_types": (GroupKFold(5), df["check"].values),
    }
    for name, (sp, g) in splits.items():
        pred, m = cv(X, y, sp, g)
        m["confusion_matrix"] = plot_cm(y, pred, f"Random Forest, split {name}",
                                        os.path.join(out, f"confusion_{name}.png"))
        m["confusion_labels"] = CLASSES
        res[name] = m

    # same Split B without the two deliberately-vulnerable training repos
    keep = ~df["intentionally_vulnerable"].astype(str).eq("True")
    _, m = cv(X[keep].reset_index(drop=True), y[keep.values], GroupKFold(5), df.loc[keep, "repo"].values)
    res["B_unseen_repos_without_goat_repos"] = m

    # SHAP on a model trained on all records
    model = rf().fit(X, y)
    sv = shap.TreeExplainer(model).shap_values(X)
    sv = np.stack(sv, -1) if isinstance(sv, list) else sv          # (n, features, classes)
    imp_col = np.abs(sv).mean(axis=(0, 2))
    groups = {f: [i for i, c in enumerate(X.columns) if c == f or c.startswith(f + "_")] for f in FEATURES}
    imp = {f: float(imp_col[idx].sum()) for f, idx in groups.items()}
    imp = dict(sorted(imp.items(), key=lambda kv: -kv[1]))
    res["shap_mean_abs_by_feature"] = {k: round(v, 4) for k, v in imp.items()}
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.barh(list(imp)[::-1], list(imp.values())[::-1], color="#3b6fb6")
    ax.set_xlabel("mean |SHAP value| (all classes)"); ax.set_title("Which features drive the predicted risk")
    fig.tight_layout(); fig.savefig(os.path.join(out, "shap_importance.png"), dpi=150); plt.close(fig)
    ci = list(model.classes_).index("Critical")
    plt.figure()
    shap.summary_plot(sv[:, :, ci], X, show=False, max_display=15)
    plt.title("SHAP for class Critical"); plt.tight_layout()
    plt.savefig(os.path.join(out, "shap_summary_critical.png"), dpi=150); plt.close("all")

    # measured label: did developers fix it later?
    fx = df[df["fixed_later"].notna()].reset_index(drop=True)
    Xf, yf = encode(fx), fx["fixed_later"].astype(int).values
    probs = np.zeros(len(yf)); f1s = []
    for tr, te in GroupKFold(5).split(Xf, yf, fx["repo"].values):
        m = RandomForestClassifier(n_estimators=300, class_weight="balanced", min_samples_leaf=2,
                                   random_state=42, n_jobs=-1).fit(Xf.iloc[tr], yf[tr])
        probs[te] = m.predict_proba(Xf.iloc[te])[:, 1]
        f1s.append(f1_score(yf[te], (probs[te] > 0.5).astype(int), average="macro", zero_division=0))
    res["fixed_later_model"] = {
        "n_records": len(fx), "fix_rate": round(float(yf.mean()), 3),
        "macro_f1_unseen_repos": round(float(np.mean(f1s)), 3),
        "roc_auc_unseen_repos": round(float(roc_auc_score(yf, probs)), 3),
        "fix_rate_by_tfsec_severity": fx.groupby("risk_label")["fixed_later"].mean().round(3).to_dict(),
    }
    json.dump(res, open(os.path.join(out, "metrics.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
