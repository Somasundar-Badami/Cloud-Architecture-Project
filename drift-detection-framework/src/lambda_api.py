"""
lambda_api.py -- AWS Lambda behind API Gateway (HTTP API, payload v2.0).
Every route requires a Cognito JWT; API Gateway enforces this before the
Lambda runs (terraform/api.tf).

Routes:
  GET  /drifts            latest records (newest first), ?limit=N (max 200)
  GET  /resources         latest record per monitored resource
  POST /scan              run the detector now (synchronous invoke), returns its summary
  POST /analyze           analyze a custom desired/actual JSON pair; nothing is stored
                          body: {"desired": {...}, "actual": {...},
                                 "resource_type": "s3_bucket|security_group|iam_policy",
                                 "drift_frequency": 0}

Environment variables: TABLE_NAME, DETECTOR_FUNCTION_NAME, MODEL_PATH (optional)
"""

import json
import os

import boto3

from drift_pipeline import SUPPORTED_KINDS, analyze, from_dynamo
from portable_model import PortableRiskModel

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = None
MAX_LIMIT = 200


def _model():
    global _MODEL
    if _MODEL is None:
        _MODEL = PortableRiskModel.load(os.environ.get("MODEL_PATH", os.path.join(_HERE, "portable_model.json")))
    return _MODEL


def _response(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body, default=str)}


def _all_records(table):
    items, kwargs = [], {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    records = [from_dynamo(i) for i in items]
    for r in records:
        r["changes"] = json.loads(r.pop("changes_json", "[]"))
    return sorted(records, key=lambda r: r["detected_at"], reverse=True)


def list_drifts(table, query):
    try:
        limit = max(1, min(MAX_LIMIT, int((query or {}).get("limit", 50))))
    except ValueError:
        return _response(400, {"error": "limit must be an integer"})
    return _response(200, {"records": _all_records(table)[:limit]})


def list_resources(table):
    latest = {}
    for record in _all_records(table):
        latest.setdefault(record["resource_id"], record)
    return _response(200, {"resources": list(latest.values())})


def run_scan_now(lambda_client, function_name):
    resp = lambda_client.invoke(FunctionName=function_name, InvocationType="RequestResponse",
                                Payload=json.dumps({"trigger": "api"}).encode())
    payload = json.loads(resp["Payload"].read() or b"null")
    if resp.get("FunctionError"):
        return _response(502, {"error": "detector failed", "detail": payload})
    return _response(200, payload)


def analyze_custom(body_text):
    try:
        body = json.loads(body_text or "")
    except json.JSONDecodeError as e:
        return _response(400, {"error": f"request body is not valid JSON: {e}"})
    if not isinstance(body, dict):
        return _response(400, {"error": "request body must be a JSON object"})
    desired, actual = body.get("desired"), body.get("actual")
    kind = body.get("resource_type")
    if not isinstance(desired, dict) or not isinstance(actual, dict):
        return _response(400, {"error": "'desired' and 'actual' must both be JSON objects"})
    if kind not in SUPPORTED_KINDS:
        return _response(400, {"error": f"'resource_type' must be one of {sorted(SUPPORTED_KINDS)}"})
    try:
        frequency = int(body.get("drift_frequency", 0))
    except (TypeError, ValueError):
        return _response(400, {"error": "'drift_frequency' must be an integer"})
    if frequency < 0:
        return _response(400, {"error": "'drift_frequency' must be >= 0"})
    return _response(200, analyze(desired, actual, kind, frequency, _model()))


def handler(event, context):
    route = event.get("routeKey", "")
    if route == "GET /drifts":
        return list_drifts(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]), event.get("queryStringParameters"))
    if route == "GET /resources":
        return list_resources(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    if route == "POST /scan":
        return run_scan_now(boto3.client("lambda"), os.environ["DETECTOR_FUNCTION_NAME"])
    if route == "POST /analyze":
        body = event.get("body")
        if event.get("isBase64Encoded") and body:
            import base64
            body = base64.b64decode(body).decode()
        return analyze_custom(body)
    return _response(404, {"error": f"unknown route {route!r}"})
