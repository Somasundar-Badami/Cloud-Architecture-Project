"""
lambda_detector.py -- AWS Lambda entry point for the scheduled drift scan.

Triggers (configured in terraform/pipeline.tf):
  - EventBridge schedule (default hourly)
  - AWS Config configuration-change events (only if enable_aws_config=true)
  - Synchronous invoke from the API (POST /scan)

Environment variables:
  DESIRED_STATE_BUCKET, DESIRED_STATE_KEY -- desired-state document written by Terraform
  TABLE_NAME                              -- DynamoDB drift-records table
  TOPIC_ARN                               -- SNS topic for High/Critical alerts
  MODEL_PATH                              -- optional, defaults to portable_model.json next to this file
"""

import json
import os

import boto3

from drift_pipeline import emf_metrics, load_desired_document, run_scan
from portable_model import PortableRiskModel

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:  # loaded once per warm Lambda container
        _MODEL = PortableRiskModel.load(os.environ.get("MODEL_PATH", os.path.join(_HERE, "portable_model.json")))
    return _MODEL


def _trigger(event):
    if isinstance(event, dict):
        if event.get("source") == "aws.config":
            return "aws_config"
        if event.get("source") == "aws.events" or event.get("detail-type") == "Scheduled Event":
            return "schedule"
        if event.get("trigger"):
            return str(event["trigger"])
    return "manual"


def handler(event, context):
    clients = {"s3": boto3.client("s3"), "ec2": boto3.client("ec2"), "iam": boto3.client("iam")}
    document = load_desired_document(clients["s3"], os.environ["DESIRED_STATE_BUCKET"], os.environ["DESIRED_STATE_KEY"])
    table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    records = run_scan(document, clients, table, boto3.client("sns"), os.environ["TOPIC_ARN"], _model(),
                       trigger=_trigger(event))

    function_name = getattr(context, "function_name", "local")
    print(json.dumps(emf_metrics(records, function_name)))
    return {
        "scanned": len(records),
        "records": [
            {k: r[k] for k in ("resource_id", "detected_at", "status", "has_drift", "changed_attributes",
                               "predicted_label", "alert_sent", "error_message")}
            for r in records
        ],
    }
