"""
findings_analytics.py

Pure helpers that turn the findings returned by the deployed API
(GET /findings and GET /findings/{resource}) into things the dashboard
can show: a risk trend over time, filtered views and a CSV export.

No Streamlit calls in here, so it is unit-testable.
"""

from typing import Any, Dict, Iterable, List

import pandas as pd

# Ordinal score per label. "Review" (an attribute outside the model's
# schema) sits between Medium and High: it needs a human, but the model
# did not call it dangerous.
RISK_SCORE = {"No drift": 0, "Low": 1, "Medium": 2, "Review": 2.5, "High": 3, "Critical": 4}


def finding_label(finding: Dict[str, Any]) -> str:
    """The label the dashboard shows: the model's risk label, or 'No drift'."""
    return finding["risk_label"] if finding.get("has_drift") else "No drift"


def risk_trend(findings: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    """
    One row per scan time with the worst risk score seen across all
    resources in that scan and how many resources had drifted.

    Columns: detected_at (datetime, UTC), worst_score, worst_label,
    drifted_resources, scanned_resources. Empty input gives an empty
    frame with the same columns.
    """
    columns = ["detected_at", "worst_score", "worst_label", "drifted_resources", "scanned_resources"]
    rows = [{
        "detected_at": f["detected_at"],
        "label": finding_label(f),
        "score": RISK_SCORE.get(finding_label(f), 0),
        "drifted": bool(f.get("has_drift")),
    } for f in findings]
    if not rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(rows)
    # Every resource in one scan shares the same timestamp to the second.
    df["detected_at"] = pd.to_datetime(df["detected_at"], utc=True).dt.floor("s")
    worst = df.loc[df.groupby("detected_at")["score"].idxmax(), ["detected_at", "score", "label"]]
    counts = df.groupby("detected_at").agg(drifted_resources=("drifted", "sum"),
                                           scanned_resources=("drifted", "size")).reset_index()
    out = worst.merge(counts, on="detected_at").rename(columns={"score": "worst_score", "label": "worst_label"})
    out["drifted_resources"] = out["drifted_resources"].astype(int)
    return out.sort_values("detected_at").reset_index(drop=True)[columns]
