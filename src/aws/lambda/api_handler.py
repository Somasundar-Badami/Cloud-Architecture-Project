"""
api_handler.py  --  AWS Lambda behind API Gateway (HTTP API, Cognito JWT auth)

Routes:
  GET  /findings              latest finding per monitored resource
  GET  /findings/{resource}   full history for one resource (newest first)
  POST /scan                  run the detector now (async invoke)

API Gateway's JWT authorizer validates the Cognito token before this
function runs; the caller's identity is read from the request context
only for audit logging.
"""

import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key


def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    return str(o)


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _caller(event):
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    return claims.get("email") or claims.get("username") or claims.get("sub", "unknown")


def latest_findings(table, resource_ids):
    out = []
    for rid in resource_ids:
        resp = table.query(KeyConditionExpression=Key("resource_id").eq(rid), ScanIndexForward=False, Limit=1)
        out.extend(resp.get("Items", []))
    return out


def lambda_handler(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["FINDINGS_TABLE"])
    resources = json.loads(os.environ["DESIRED_STATE_JSON"])
    resource_ids = [r["resource_id"] for r in resources]
    route = event.get("routeKey", "")
    print(json.dumps({"route": route, "caller": _caller(event)}))

    if route == "GET /findings":
        return _response(200, {"findings": latest_findings(table, resource_ids)})

    if route == "GET /findings/{resource}":
        rid = event.get("pathParameters", {}).get("resource")
        if rid not in resource_ids:
            return _response(404, {"error": f"Unknown resource {rid!r}"})
        resp = table.query(KeyConditionExpression=Key("resource_id").eq(rid), ScanIndexForward=False, Limit=50)
        return _response(200, {"resource_id": rid, "history": resp.get("Items", [])})

    if route == "POST /scan":
        boto3.client("lambda").invoke(
            FunctionName=os.environ["DETECTOR_FUNCTION_NAME"],
            InvocationType="Event",
            Payload=json.dumps({"source": "api", "requested_by": _caller(event)}).encode(),
        )
        return _response(202, {"status": "scan started"})

    return _response(404, {"error": f"No route {route!r}"})
