"""
drift_pipeline.py

The AWS-side pipeline, written as plain functions with injected boto3
clients so it can be unit-tested without AWS (see tests/test_drift_pipeline.py)
and reused by both Lambda handlers:

    desired-state document (S3, written by Terraform)
        -> collect actual state (boto3: S3 / EC2 / IAM)
        -> normalize (aws_normalizer.py)
        -> detect_drift (drift_engine.py, unchanged)
        -> extract_features (feature_extraction.py, unchanged)
        -> risk prediction + SHAP (portable_model.py)
        -> DynamoDB record
        -> SNS alert for High/Critical (once per distinct drift)

drift_frequency is computed from real history: the number of earlier
records for the same resource that had drift within the last
DRIFT_FREQUENCY_WINDOW_DAYS days.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from aws_normalizer import (
    normalize_iam_role_actual_state,
    normalize_s3_actual_state,
    normalize_sg_actual_state,
)
from aws_state import (
    AWSConfigurationError,
    fetch_iam_role_raw_config,
    fetch_s3_bucket_raw_config,
    fetch_security_group_raw_config,
)
from drift_engine import detect_drift
from feature_extraction import extract_features

ALERT_LABELS = {"High", "Critical"}
DRIFT_FREQUENCY_WINDOW_DAYS = 30
SUPPORTED_KINDS = {"s3_bucket", "security_group", "iam_policy"}

STATUS_OK = "ok"
STATUS_UNCLASSIFIED = "unclassified_attribute"
STATUS_COLLECTION_ERROR = "collection_error"


# ---------------------------------------------------------------------------
# Desired state + actual state collection
# ---------------------------------------------------------------------------

def load_desired_document(s3_client, bucket: str, key: str) -> Dict[str, Any]:
    body = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    document = json.loads(body)
    for resource in document["resources"]:
        if resource["kind"] not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported resource kind in desired-state document: {resource['kind']}")
    return document


def collect_actual_state(resource: Dict[str, Any], clients: Dict[str, Any]) -> Dict[str, Any]:
    kind, desired = resource["kind"], resource["desired"]
    if kind == "s3_bucket":
        raw = fetch_s3_bucket_raw_config(clients["s3"], desired["bucket_name"])
        # account_id=None -> owner-only policies normalize to the same
        # placeholder principal the desired state uses
        return normalize_s3_actual_state(raw)
    if kind == "security_group":
        raw = fetch_security_group_raw_config(clients["ec2"], desired["sg_id"])
        return normalize_sg_actual_state(raw, desired["instance_name"], desired["internal_service_port"]["port"])
    raw = fetch_iam_role_raw_config(clients["iam"], desired["entity_name"], resource["inline_policy_name"])
    return normalize_iam_role_actual_state(raw)


# ---------------------------------------------------------------------------
# Analysis (no AWS calls)
# ---------------------------------------------------------------------------

def analyze(desired: Dict[str, Any], actual: Dict[str, Any], kind: str, drift_frequency: int, model) -> Dict[str, Any]:
    drift_result = detect_drift(desired, actual)
    result: Dict[str, Any] = {
        "status": STATUS_OK,
        "has_drift": drift_result["has_drift"],
        "num_changes": drift_result["num_changes"],
        "changed_attributes": drift_result["changed_attributes"],
        "changes": drift_result["changes"],
        "drift_frequency": drift_frequency,
        "features": None,
        "explanation": None,
        "error_message": None,
    }
    try:
        features = extract_features(kind, drift_result, drift_frequency)
    except KeyError as e:
        result["status"] = STATUS_UNCLASSIFIED
        result["error_message"] = str(e).strip('"')
        return result
    result["features"] = features
    result["explanation"] = model.explain(features)
    return result


def drift_signature(result: Dict[str, Any]) -> str:
    """Identifies 'the same drift' across runs (same changes, same label)."""
    label = (result.get("explanation") or {}).get("predicted_label")
    payload = json.dumps([result.get("status"), label, result.get("changes")], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def should_alert(result: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> bool:
    label = (result.get("explanation") or {}).get("predicted_label")
    if not result["has_drift"] or label not in ALERT_LABELS:
        return False
    return previous is None or previous.get("drift_signature") != drift_signature(result)


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------

def to_dynamo(value: Any) -> Any:
    """floats -> Decimal (boto3's DynamoDB resource rejects float)."""
    return json.loads(json.dumps(value, default=str), parse_float=Decimal)


def from_dynamo(value: Any) -> Any:
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def latest_record(table, resource_id: str) -> Optional[Dict[str, Any]]:
    resp = table.query(
        KeyConditionExpression="resource_id = :r",
        ExpressionAttributeValues={":r": resource_id},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return from_dynamo(items[0]) if items else None


def count_recent_drifts(table, resource_id: str, now: datetime) -> int:
    since = (now - timedelta(days=DRIFT_FREQUENCY_WINDOW_DAYS)).isoformat()
    kwargs = {
        "KeyConditionExpression": "resource_id = :r AND detected_at >= :since",
        "FilterExpression": "has_drift = :t",
        "ExpressionAttributeValues": {":r": resource_id, ":since": since, ":t": True},
        "Select": "COUNT",
    }
    total = 0
    while True:
        resp = table.query(**kwargs)
        total += resp.get("Count", 0)
        if "LastEvaluatedKey" not in resp:
            return total
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def build_record(resource: Dict[str, Any], result: Dict[str, Any], now: datetime, trigger: str,
                 model_sha256: Optional[str]) -> Dict[str, Any]:
    explanation = result.get("explanation") or {}
    return {
        "resource_id": resource["resource_id"],
        "detected_at": now.isoformat(),
        "record_id": str(uuid.uuid4()),
        "resource_type": resource["kind"],
        "trigger": trigger,
        "status": result["status"],
        "has_drift": result["has_drift"],
        "num_changes": result["num_changes"],
        "changed_attributes": result["changed_attributes"],
        # old/new values have arbitrary types -> stored as one JSON string
        "changes_json": json.dumps(result["changes"], default=str),
        "drift_frequency": result["drift_frequency"],
        "features": result["features"],
        "predicted_label": explanation.get("predicted_label"),
        "probabilities": explanation.get("probabilities"),
        "base_value": explanation.get("base_value"),
        "shap_values": explanation.get("shap_values"),
        "shap_top_positive": explanation.get("top_positive_contributors"),
        "shap_top_negative": explanation.get("top_negative_contributors"),
        "additivity_error": explanation.get("additivity_error"),
        "error_message": result.get("error_message"),
        "drift_signature": drift_signature(result),
        "model_sha256": model_sha256,
        "alert_sent": False,
    }


# ---------------------------------------------------------------------------
# SNS
# ---------------------------------------------------------------------------

def format_alert(record: Dict[str, Any]) -> Dict[str, str]:
    label = record["predicted_label"]
    subject = f"[{label}] Infrastructure drift on {record['resource_id']}"[:100]
    lines = [
        f"Risk level: {label} (Random Forest, primary model)",
        f"Resource: {record['resource_id']} ({record['resource_type']})",
        f"Detected at: {record['detected_at']} (trigger: {record['trigger']})",
        "",
        "Changes (desired -> actual):",
    ]
    for change in json.loads(record["changes_json"]):
        lines.append(f"  {change['attribute']}: {change['old_value']!r} -> {change['new_value']!r}")
    lines += ["", "Class probabilities:"]
    for name, p in record["probabilities"].items():
        lines.append(f"  {name}: {p:.3f}")
    lines += ["", f"Top SHAP contributors toward '{label}':"]
    for feature, value in record["shap_top_positive"] or []:
        lines.append(f"  {feature}: {value:+.4f}")
    lines += ["", f"Drift occurrences for this resource in the last {DRIFT_FREQUENCY_WINDOW_DAYS} days "
                  f"(before this one): {record['drift_frequency']}",
              f"Record id: {record['record_id']}"]
    return {"Subject": subject, "Message": "\n".join(lines)}


# ---------------------------------------------------------------------------
# One full scan
# ---------------------------------------------------------------------------

def run_scan(document: Dict[str, Any], clients: Dict[str, Any], table, sns_client, topic_arn: str, model,
             trigger: str = "schedule", now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    records = []
    for resource in document["resources"]:
        now_i = now or datetime.now(timezone.utc)
        previous = latest_record(table, resource["resource_id"])
        frequency = count_recent_drifts(table, resource["resource_id"], now_i)
        try:
            actual = collect_actual_state(resource, clients)
            result = analyze(resource["desired"], actual, resource["kind"], frequency, model)
        except AWSConfigurationError as e:
            # e.g. resource deleted outside Terraform -- recorded, never guessed
            result = {
                "status": STATUS_COLLECTION_ERROR, "has_drift": e.category == "not_found",
                "num_changes": 0, "changed_attributes": [], "changes": [],
                "drift_frequency": frequency, "features": None, "explanation": None,
                "error_message": f"{e.category}: {e.message}",
            }
        record = build_record(resource, result, now_i, trigger, model.source.get("model_sha256"))
        if should_alert(result, previous):
            sns_client.publish(TopicArn=topic_arn, **format_alert(record))
            record["alert_sent"] = True
        table.put_item(Item=to_dynamo(record))
        records.append(record)
    return records


def emf_metrics(records: List[Dict[str, Any]], function_name: str) -> Dict[str, Any]:
    """CloudWatch Embedded Metric Format -- printing this dict to stdout
    from Lambda creates custom metrics without any extra IAM permission."""
    return {
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": "DriftDetection",
                "Dimensions": [["FunctionName"]],
                "Metrics": [{"Name": n, "Unit": "Count"} for n in
                            ("ResourcesScanned", "DriftsDetected", "HighRiskDrifts", "AlertsSent", "CollectionErrors")],
            }],
        },
        "FunctionName": function_name,
        "ResourcesScanned": len(records),
        "DriftsDetected": sum(1 for r in records if r["has_drift"]),
        "HighRiskDrifts": sum(1 for r in records if r["predicted_label"] in ALERT_LABELS and r["has_drift"]),
        "AlertsSent": sum(1 for r in records if r["alert_sent"]),
        "CollectionErrors": sum(1 for r in records if r["status"] == STATUS_COLLECTION_ERROR),
    }
