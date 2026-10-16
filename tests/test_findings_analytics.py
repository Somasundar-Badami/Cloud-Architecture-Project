"""
tests/test_findings_analytics.py

Tests for src/frontend/findings_analytics.py using hand-written findings
shaped like the items the detector Lambda stores in DynamoDB.
"""

import findings_analytics as fa


def _finding(rid, at, has_drift, label="Low", rtype="security_group"):
    return {"resource_id": rid, "resource_type": rtype, "detected_at": at,
            "has_drift": has_drift, "risk_label": label if has_drift else "Low",
            "changes": [{"attribute": "inbound_ssh.source_cidr", "old_value": "10.0.0.0/8",
                         "new_value": "0.0.0.0/0"}] if has_drift else []}


def test_finding_label_no_drift_ignores_risk_label():
    assert fa.finding_label(_finding("a", "2026-10-01T00:00:00+00:00", False)) == "No drift"


def test_finding_label_uses_model_label_when_drifted():
    assert fa.finding_label(_finding("a", "2026-10-01T00:00:00+00:00", True, "Critical")) == "Critical"


def test_risk_score_is_monotonic_in_severity():
    order = ["No drift", "Low", "Medium", "High", "Critical"]
    scores = [fa.RISK_SCORE[k] for k in order]
    assert scores == sorted(scores)


def test_risk_trend_empty_input_returns_empty_frame_with_columns():
    df = fa.risk_trend([])
    assert df.empty
    assert list(df.columns) == ["detected_at", "worst_score", "worst_label",
                                "drifted_resources", "scanned_resources"]


def test_risk_trend_one_row_per_scan_with_worst_label():
    t1, t2 = "2026-10-01T10:00:00.123456+00:00", "2026-10-01T11:00:00.654321+00:00"
    findings = [
        _finding("sg", t1, True, "Critical"),
        _finding("bucket", t1, True, "Medium", "s3_bucket"),
        _finding("role", t1, False, rtype="iam_policy"),
        _finding("sg", t2, False),
        _finding("bucket", t2, False, rtype="s3_bucket"),
    ]
    df = fa.risk_trend(findings)
    assert len(df) == 2
    first, second = df.iloc[0], df.iloc[1]
    assert first["worst_label"] == "Critical" and first["worst_score"] == 4
    assert first["drifted_resources"] == 2 and first["scanned_resources"] == 3
    assert second["worst_label"] == "No drift" and second["drifted_resources"] == 0


def test_risk_trend_sorted_oldest_first_regardless_of_input_order():
    findings = [_finding("sg", "2026-10-02T00:00:00+00:00", True, "High"),
                _finding("sg", "2026-10-01T00:00:00+00:00", False)]
    df = fa.risk_trend(findings)
    assert df["detected_at"].is_monotonic_increasing
    assert list(df["worst_label"]) == ["No drift", "High"]


def test_risk_trend_review_label_scored_between_medium_and_high():
    df = fa.risk_trend([_finding("sg", "2026-10-01T00:00:00+00:00", True, "Review")])
    assert fa.RISK_SCORE["Medium"] < df.iloc[0]["worst_score"] < fa.RISK_SCORE["High"]
