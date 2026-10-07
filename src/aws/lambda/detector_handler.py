"""
detector_handler.py  --  AWS Lambda: InfraDriftGuard drift detector

Triggered by an EventBridge schedule (and on demand via POST /scan).

For every monitored resource declared in DESIRED_STATE_JSON (rendered by
Terraform, so the IaC stays the single source of truth):
  1. Collect the LIVE configuration with boto3 (S3 / Security Group / IAM role)
  2. Normalize it into the project schema
  3. detect_drift(desired, actual)                 -- src/backend/drift_engine.py
  4. extract_features(...)                          -- src/backend/feature_extraction.py
     drift_frequency = number of earlier drift findings for this resource
     (read from DynamoDB -- a real historical count, not a constant)
  5. Classify risk with the exported Random Forest  -- rf_predict.py
  6. Store the finding in DynamoDB, publish a CloudWatch metric, alert via
     SNS when risk >= ALERT_MIN_RISK, and optionally auto-remediate the
     two Critical patterns that have a safe, well-defined fix.

Environment variables (all set by Terraform):
  DESIRED_STATE_JSON   list of {resource_id, resource_type, desired}
  FINDINGS_TABLE       DynamoDB table name
  ALERT_TOPIC_ARN      SNS topic ARN
  ALERT_MIN_RISK       Low | Medium | High | Critical   (default High)
  AUTO_REMEDIATE       "true" to enable auto-remediation (default false)
  METRIC_NAMESPACE     CloudWatch namespace (default InfraDriftGuard)
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

from drift_engine import detect_drift
from feature_extraction import ATTRIBUTE_KNOWLEDGE_BASE, extract_features
from rf_predict import RandomForestJSON
from aws_state import fetch_s3_bucket_raw_config
from aws_normalizer import normalize_s3_actual_state
from sg_iam_collectors import (
    fetch_security_group,
    normalize_security_group,
    fetch_iam_role,
    normalize_iam_role,
)

RISK_ORDER = ["Low", "Medium", "High", "Critical"]
PUBLIC_CIDR = "0.0.0.0/0"

_MODEL: Optional[RandomForestJSON] = None


def _model() -> RandomForestJSON:
    global _MODEL
    if _MODEL is None:  # loaded once per warm container
        _MODEL = RandomForestJSON.load()
    return _MODEL


def _clients():
    return {
        "s3": boto3.client("s3"),
        "ec2": boto3.client("ec2"),
        "iam": boto3.client("iam"),
        "dynamodb": boto3.resource("dynamodb"),
        "sns": boto3.client("sns"),
        "cloudwatch": boto3.client("cloudwatch"),
    }


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect_actual_state(resource: Dict[str, Any], clients: Dict[str, Any], account_id: str) -> Dict[str, Any]:
    rtype, rid = resource["resource_type"], resource["resource_id"]
    if rtype == "s3_bucket":
        raw = fetch_s3_bucket_raw_config(clients["s3"], rid)
        return normalize_s3_actual_state(raw, account_id=account_id)
    if rtype == "security_group":
        port = resource.get("desired", {}).get("internal_service_port", {}).get("port", 5432)
        return normalize_security_group(fetch_security_group(clients["ec2"], rid), service_port=port)
    if rtype == "iam_policy":
        role, policy = fetch_iam_role(clients["iam"], rid)
        return normalize_iam_role(role, policy)
    raise ValueError(f"Unsupported resource_type {rtype!r}")


# ---------------------------------------------------------------------------
# Analysis (pure -- unit-testable without AWS)
# ---------------------------------------------------------------------------

def analyze(resource_type: str, desired: Dict[str, Any], actual: Dict[str, Any], drift_frequency: int) -> Dict[str, Any]:
    drift = detect_drift(desired, actual)
    known = [c for c in drift["changes"] if c["attribute"] in ATTRIBUTE_KNOWLEDGE_BASE]
    unknown = [c for c in drift["changes"] if c["attribute"] not in ATTRIBUTE_KNOWLEDGE_BASE]

    result: Dict[str, Any] = {
        "has_drift": drift["has_drift"],
        "changes": drift["changes"],
        "unmodelled_attributes": [c["attribute"] for c in unknown],
    }

    if known or not drift["has_drift"]:
        features = extract_features(resource_type, {"changes": known}, drift_frequency)
        prediction = _model().predict(features)
        result.update(features=features, **prediction)
    else:
        # Every change is outside the model's 21-attribute knowledge base
        # (e.g. a whole rule deleted). Never guess a label for it -- flag it
        # for human review instead.
        result.update(features=None, risk_label="Review", confidence=None, probabilities=None)

    if unknown and result["risk_label"] in ("Low",):
        result["risk_label"] = "Review"
    return result


def should_alert(risk_label: str, min_risk: str) -> bool:
    if risk_label == "Review":
        return True
    return RISK_ORDER.index(risk_label) >= RISK_ORDER.index(min_risk)


# ---------------------------------------------------------------------------
# Remediation (opt-in)
# ---------------------------------------------------------------------------

def remediate(resource: Dict[str, Any], analysis: Dict[str, Any], clients: Dict[str, Any]) -> List[str]:
    """Only reverts changes whose safe state is unambiguous. Everything
    else is left for a human (and Terraform apply)."""
    actions: List[str] = []
    if analysis.get("risk_label") != "Critical":
        return actions
    rid = resource["resource_id"]
    attrs = {c["attribute"]: c for c in analysis["changes"]}

    if resource["resource_type"] == "s3_bucket" and "block_public_access" in attrs:
        clients["s3"].put_public_access_block(
            Bucket=rid,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        actions.append("s3:re-enabled block_public_access")

    if resource["resource_type"] == "security_group":
        for attr, port in (("inbound_ssh.source_cidr", 22), ("inbound_rdp.source_cidr", 3389)):
            if attr in attrs and attrs[attr]["new_value"] == PUBLIC_CIDR:
                clients["ec2"].revoke_security_group_ingress(
                    GroupId=rid,
                    IpPermissions=[{"IpProtocol": "tcp", "FromPort": port, "ToPort": port,
                                    "IpRanges": [{"CidrIp": PUBLIC_CIDR}]}],
                )
                actions.append(f"ec2:revoked {PUBLIC_CIDR} on port {port}")
    return actions


# ---------------------------------------------------------------------------
# Persistence / notification
# ---------------------------------------------------------------------------

def _to_dynamo(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str), parse_float=Decimal)


def previous_drift_count(table, resource_id: str) -> int:
    resp = table.query(
        KeyConditionExpression=Key("resource_id").eq(resource_id),
        Select="COUNT",
        FilterExpression="has_drift = :t",
        ExpressionAttributeValues={":t": True},
    )
    return int(resp.get("Count", 0))


def format_alert(resource: Dict[str, Any], analysis: Dict[str, Any], remediation: List[str]) -> str:
    lines = [
        f"InfraDriftGuard detected configuration drift",
        f"Resource : {resource['resource_type']} / {resource['resource_id']}",
        f"Risk     : {analysis['risk_label']}"
        + (f" (confidence {analysis['confidence']:.0%})" if analysis.get("confidence") is not None else ""),
        "",
        "Changes (desired -> actual):",
    ]
    for c in analysis["changes"]:
        lines.append(f"  - {c['attribute']}: {c['old_value']!r} -> {c['new_value']!r}")
    if analysis["unmodelled_attributes"]:
        lines.append(f"Needs manual review: {', '.join(analysis['unmodelled_attributes'])}")
    if remediation:
        lines += ["", "Auto-remediation applied:"] + [f"  - {a}" for a in remediation]
    else:
        lines += ["", "Fix: run `terraform apply` to restore the declared state."]
    return "\n".join(lines)


def lambda_handler(event, context):
    resources = json.loads(os.environ["DESIRED_STATE_JSON"])
    min_risk = os.environ.get("ALERT_MIN_RISK", "High")
    auto_remediate = os.environ.get("AUTO_REMEDIATE", "false").lower() == "true"
    namespace = os.environ.get("METRIC_NAMESPACE", "InfraDriftGuard")
    account_id = context.invoked_function_arn.split(":")[4] if context else None

    clients = _clients()
    table = clients["dynamodb"].Table(os.environ["FINDINGS_TABLE"])
    scan_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    summary = {"scan_id": scan_id, "scanned_at": now, "results": []}
    started = time.time()

    for resource in resources:
        rid = resource["resource_id"]
        try:
            actual = collect_actual_state(resource, clients, account_id)
            freq = previous_drift_count(table, rid)
            analysis = analyze(resource["resource_type"], resource["desired"], actual, freq)
        except Exception as e:  # one broken resource must not stop the scan
            print(json.dumps({"level": "ERROR", "resource_id": rid, "error": repr(e)}))
            summary["results"].append({"resource_id": rid, "error": str(e)})
            continue

        remediation: List[str] = []
        if analysis["has_drift"] and auto_remediate:
            try:
                remediation = remediate(resource, analysis, clients)
            except Exception as e:
                print(json.dumps({"level": "ERROR", "resource_id": rid, "remediation_error": repr(e)}))

        item = {
            "resource_id": rid,
            "detected_at": now,
            "scan_id": scan_id,
            "resource_type": resource["resource_type"],
            "has_drift": analysis["has_drift"],
            "risk_label": analysis["risk_label"],
            "confidence": analysis.get("confidence"),
            "probabilities": analysis.get("probabilities"),
            "features": analysis.get("features"),
            "changes": analysis["changes"],
            "unmodelled_attributes": analysis["unmodelled_attributes"],
            "remediation": remediation,
        }
        table.put_item(Item=_to_dynamo(item))

        clients["cloudwatch"].put_metric_data(
            Namespace=namespace,
            MetricData=[{
                "MetricName": "DriftDetected",
                "Dimensions": [{"Name": "RiskLevel", "Value": analysis["risk_label"] if analysis["has_drift"] else "None"}],
                "Value": 1 if analysis["has_drift"] else 0,
                "Unit": "Count",
            }],
        )

        if analysis["has_drift"] and should_alert(analysis["risk_label"], min_risk):
            clients["sns"].publish(
                TopicArn=os.environ["ALERT_TOPIC_ARN"],
                Subject=f"[{analysis['risk_label']}] Drift on {rid}"[:100],
                Message=format_alert(resource, analysis, remediation),
            )

        print(json.dumps({"level": "INFO", "resource_id": rid, "has_drift": analysis["has_drift"],
                          "risk": analysis["risk_label"], "remediation": remediation}))
        summary["results"].append({k: item[k] for k in ("resource_id", "resource_type", "has_drift", "risk_label", "remediation")})

    summary["duration_ms"] = int((time.time() - started) * 1000)
    return summary
