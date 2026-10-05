"""
tests/test_drift_pipeline.py

End-to-end tests of the AWS pipeline (drift_pipeline.py, lambda_detector.py,
lambda_api.py) against moto's in-memory AWS -- real boto3 calls, no AWS
account, no network. The mocked account is built to mirror what
terraform/*.tf deploys (same settings, same desired-state document shape).

Run with:
    pytest tests/test_drift_pipeline.py -v
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import drift_pipeline  # noqa: E402
import lambda_api  # noqa: E402
import lambda_detector  # noqa: E402
from portable_model import PortableRiskModel  # noqa: E402

REGION = "us-east-1"
PORTABLE_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "portable_model.json")
BUCKET = "drift-demo-sandbox-abcd1234"
ARTIFACTS = "drift-demo-sandbox-artifacts-abcd1234"
DESIRED_KEY = "desired-state/desired_state.json"
TABLE = "drift-demo-sandbox-drift-records"
ROLE = "drift-demo-sandbox-app-role"
POLICY = "drift-demo-sandbox-app-access"
SG_NAME = "drift-demo-sandbox-web"


@pytest.fixture(scope="module")
def model():
    return PortableRiskModel.load(PORTABLE_PATH)


@pytest.fixture
def aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                 "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": REGION}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        yield _build_account(monkeypatch)


def _build_account(monkeypatch):
    s3 = boto3.client("s3", region_name=REGION)
    ec2 = boto3.client("ec2", region_name=REGION)
    iam = boto3.client("iam", region_name=REGION)
    account = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]

    # --- monitored S3 bucket (terraform/main.tf) ---
    s3.create_bucket(Bucket=BUCKET)
    s3.put_public_access_block(Bucket=BUCKET, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_encryption(Bucket=BUCKET, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    s3.put_bucket_acl(Bucket=BUCKET, ACL="private")

    # --- monitored security group (terraform/monitored_resources.tf) ---
    vpc_id = ec2.create_vpc(CidrBlock="10.20.0.0/16")["Vpc"]["VpcId"]
    sg_id = ec2.create_security_group(GroupName=SG_NAME, Description="drift demo", VpcId=vpc_id)["GroupId"]
    ec2.revoke_security_group_egress(GroupId=sg_id, IpPermissions=[
        {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])

    def tcp(port, cidr):
        return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": cidr}]}

    ec2.authorize_security_group_ingress(GroupId=sg_id, IpPermissions=[
        tcp(22, "10.0.0.0/8"), tcp(3389, "10.0.0.0/8"), tcp(443, "0.0.0.0/0"), tcp(5432, "10.0.0.0/8")])
    ec2.authorize_security_group_egress(GroupId=sg_id, IpPermissions=[
        {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "10.0.0.0/8"}]}])

    # --- monitored IAM role (terraform/monitored_resources.tf) ---
    boundary_arn = iam.create_policy(PolicyName="drift-demo-sandbox-boundary", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}))["Policy"]["Arn"]
    trust_principal = f"arn:aws:iam::{account}:root"
    iam.create_role(RoleName=ROLE, PermissionsBoundary=boundary_arn, AssumeRolePolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": {"AWS": trust_principal}, "Action": "sts:AssumeRole"}]}))
    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY, PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Sid": "PrimaryAccess", "Effect": "Allow", "Action": ["s3:GetObject"],
                       "Resource": [f"arn:aws:s3:::{BUCKET}/*"],
                       "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}}]}))

    # --- desired-state document (terraform/desired_state.tf) ---
    document = {
        "generated_by": "terraform",
        "resources": [
            {"resource_id": f"s3:{BUCKET}", "kind": "s3_bucket", "desired": {
                "resource_type": "aws_s3_bucket", "bucket_name": BUCKET, "block_public_access": True,
                "acl": "private", "encryption": {"enabled": True, "kms_key_id": None}, "versioning": "disabled",
                "logging": "disabled", "lifecycle_rule": None,
                "bucket_policy_principal": "arn:aws:iam::000000000000:root"}},
            {"resource_id": f"sg:{sg_id}", "kind": "security_group", "desired": {
                "resource_type": "aws_security_group", "sg_id": sg_id, "instance_name": SG_NAME,
                "inbound_ssh": {"port": 22, "source_cidr": "10.0.0.0/8"},
                "inbound_rdp": {"port": 3389, "source_cidr": "10.0.0.0/8"},
                "inbound_https": {"port": 443, "source_cidr": "0.0.0.0/0"},
                "inbound_custom": None,
                "outbound_default": {"port": "all", "destination_cidr": "10.0.0.0/8"},
                "internal_service_port": {"port": 5432, "range": "single"},
                "peer_sg_reference": None}},
            {"resource_id": f"iam:{ROLE}", "kind": "iam_policy", "inline_policy_name": POLICY, "desired": {
                "resource_type": "aws_iam_entity", "entity_name": ROLE, "actions": ["s3:GetObject"],
                "resources": [f"arn:aws:s3:::{BUCKET}/*"], "effect": "Allow", "requires_mfa": True,
                "trust_principal": trust_principal, "permissions_boundary": boundary_arn,
                "group_membership": "StandardAccess"}},
        ],
    }
    s3.create_bucket(Bucket=ARTIFACTS)
    s3.put_object(Bucket=ARTIFACTS, Key=DESIRED_KEY, Body=json.dumps(document).encode())

    # --- pipeline resources (terraform/pipeline.tf) ---
    boto3.client("dynamodb", region_name=REGION).create_table(
        TableName=TABLE, BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "resource_id", "KeyType": "HASH"},
                   {"AttributeName": "detected_at", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "resource_id", "AttributeType": "S"},
                              {"AttributeName": "detected_at", "AttributeType": "S"}])
    sns = boto3.client("sns", region_name=REGION)
    topic_arn = sns.create_topic(Name="drift-alerts")["TopicArn"]
    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.create_queue(QueueName="alert-capture")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)

    for k, v in {"DESIRED_STATE_BUCKET": ARTIFACTS, "DESIRED_STATE_KEY": DESIRED_KEY, "TABLE_NAME": TABLE,
                 "TOPIC_ARN": topic_arn, "MODEL_PATH": PORTABLE_PATH, "DETECTOR_FUNCTION_NAME": "detector"}.items():
        monkeypatch.setenv(k, v)

    return {"s3": s3, "ec2": ec2, "iam": iam, "sqs": sqs, "queue_url": queue_url, "sg_id": sg_id,
            "boundary_arn": boundary_arn, "document": document}


def _alerts(env):
    resp = env["sqs"].receive_message(QueueUrl=env["queue_url"], MaxNumberOfMessages=10)
    return [json.loads(m["Body"]) for m in resp.get("Messages", [])]


def _scan():
    return lambda_detector.handler({"source": "aws.events", "detail-type": "Scheduled Event"}, None)


def _inject_drift(env):
    """Three out-of-band changes, one per resource type."""
    env["s3"].delete_public_access_block(Bucket=BUCKET)                                  # S1
    env["ec2"].authorize_security_group_ingress(GroupId=env["sg_id"], IpPermissions=[    # E1
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
    env["iam"].delete_role_permissions_boundary(RoleName=ROLE)                            # I6


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

def test_freshly_deployed_resources_have_no_drift(aws):
    summary = _scan()
    assert summary["scanned"] == 3
    for record in summary["records"]:
        assert record["status"] == "ok", record
        assert record["has_drift"] is False, record
        assert record["predicted_label"] == "Low"
        assert record["alert_sent"] is False
    assert _alerts(aws) == []


def test_out_of_band_changes_are_detected_classified_and_alerted(aws):
    _scan()
    _inject_drift(aws)
    summary = _scan()
    by_type = {r["resource_id"].split(":")[0]: r for r in summary["records"]}

    assert by_type["s3"]["changed_attributes"] == ["block_public_access"]
    assert by_type["s3"]["predicted_label"] == "Critical"
    assert by_type["sg"]["changed_attributes"] == ["inbound_ssh.source_cidr"]
    assert by_type["sg"]["predicted_label"] == "Critical"
    assert by_type["iam"]["changed_attributes"] == ["permissions_boundary"]
    assert by_type["iam"]["predicted_label"] == "High"
    assert all(r["alert_sent"] for r in summary["records"])

    alerts = _alerts(aws)
    assert len(alerts) == 3
    assert {a["Subject"].split("]")[0] for a in alerts} == {"[Critical", "[High"}
    assert any("inbound_ssh.source_cidr: '10.0.0.0/8' -> '0.0.0.0/0'" in a["Message"] for a in alerts)


def test_unchanged_drift_is_not_re_alerted_and_frequency_counts_history(aws):
    _inject_drift(aws)
    first = _scan()
    assert len(_alerts(aws)) == 3
    second = _scan()
    assert _alerts(aws) == []
    assert all(not r["alert_sent"] for r in second["records"])

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    latest = drift_pipeline.latest_record(table, first["records"][0]["resource_id"])
    assert latest["drift_frequency"] == 1  # the first drifted scan, counted by the second
    assert latest["features"]["drift_frequency"] == 1


def test_stored_record_contains_explanation_and_raw_changes(aws):
    _inject_drift(aws)
    _scan()
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    record = drift_pipeline.latest_record(table, f"iam:{ROLE}")
    changes = json.loads(record["changes_json"])
    assert changes == [{"attribute": "permissions_boundary", "old_value": aws["boundary_arn"], "new_value": None}]
    assert set(record["probabilities"]) == {"Low", "Medium", "High", "Critical"}
    assert len(record["shap_values"]) == 30
    assert record["additivity_error"] < 1e-9
    assert "old_value" not in record["features"] and "new_value" not in record["features"]


def test_deleted_resource_is_recorded_as_collection_error(aws):
    aws["iam"].delete_role_policy(RoleName=ROLE, PolicyName=POLICY)
    aws["iam"].delete_role(RoleName=ROLE)
    summary = _scan()
    iam_record = next(r for r in summary["records"] if r["resource_id"].startswith("iam:"))
    assert iam_record["status"] == "collection_error"
    assert iam_record["has_drift"] is True
    assert iam_record["error_message"].startswith("not_found")
    assert iam_record["predicted_label"] is None


def test_drift_without_a_knowledge_base_rule_is_stored_unclassified(aws):
    aws["ec2"].revoke_security_group_ingress(GroupId=aws["sg_id"], IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
    summary = _scan()
    sg_record = next(r for r in summary["records"] if r["resource_id"].startswith("sg:"))
    assert sg_record["status"] == "unclassified_attribute"
    assert sg_record["has_drift"] is True
    assert sg_record["predicted_label"] is None
    assert sg_record["alert_sent"] is False


def test_emf_metrics_document(aws):
    _inject_drift(aws)
    records = drift_pipeline.run_scan(
        aws["document"], {"s3": aws["s3"], "ec2": aws["ec2"], "iam": aws["iam"]},
        boto3.resource("dynamodb", region_name=REGION).Table(TABLE), boto3.client("sns", region_name=REGION),
        os.environ["TOPIC_ARN"], PortableRiskModel.load(PORTABLE_PATH))
    metrics = drift_pipeline.emf_metrics(records, "fn")
    assert metrics["ResourcesScanned"] == 3
    assert metrics["DriftsDetected"] == 3
    assert metrics["HighRiskDrifts"] == 3
    assert metrics["AlertsSent"] == 3
    assert metrics["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "DriftDetection"


def test_drift_frequency_window_excludes_old_records(aws):
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    now = datetime.now(timezone.utc)
    for days_ago in (1, 5, 45):
        table.put_item(Item={"resource_id": "s3:x", "detected_at": (now - timedelta(days=days_ago)).isoformat(),
                             "has_drift": True})
    table.put_item(Item={"resource_id": "s3:x", "detected_at": (now - timedelta(days=2)).isoformat(),
                         "has_drift": False})
    assert drift_pipeline.count_recent_drifts(table, "s3:x", now) == 2


# ---------------------------------------------------------------------------
# Alert decision (pure)
# ---------------------------------------------------------------------------

def _result(label, changes, has_drift=True):
    return {"status": "ok", "has_drift": has_drift, "changes": changes,
            "explanation": {"predicted_label": label} if label else None}


def test_should_alert_rules():
    change = [{"attribute": "acl", "old_value": "private", "new_value": "public-read"}]
    critical = _result("Critical", change)
    assert drift_pipeline.should_alert(critical, None) is True
    assert drift_pipeline.should_alert(critical, {"drift_signature": drift_pipeline.drift_signature(critical)}) is False
    assert drift_pipeline.should_alert(critical, {"drift_signature": "something-else"}) is True
    assert drift_pipeline.should_alert(_result("Medium", change), None) is False
    assert drift_pipeline.should_alert(_result("Low", [], has_drift=False), None) is False
    assert drift_pipeline.should_alert(_result(None, change), None) is False


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _api(route, body=None, query=None):
    event = {"routeKey": route, "body": json.dumps(body) if isinstance(body, (dict, list)) else body,
             "queryStringParameters": query}
    resp = lambda_api.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def test_api_lists_drifts_and_latest_per_resource(aws):
    _scan()
    _inject_drift(aws)
    _scan()
    status, body = _api("GET /drifts", query={"limit": "4"})
    assert status == 200 and len(body["records"]) == 4
    times = [r["detected_at"] for r in body["records"]]
    assert times == sorted(times, reverse=True)
    assert isinstance(body["records"][0]["changes"], list)

    status, body = _api("GET /resources")
    assert status == 200 and len(body["resources"]) == 3
    assert all(r["has_drift"] for r in body["resources"])


def test_api_rejects_bad_limit(aws):
    assert _api("GET /drifts", query={"limit": "abc"})[0] == 400


def test_api_analyze_matches_scenario_s2(aws):
    desired = aws["document"]["resources"][0]["desired"]
    actual = dict(desired, acl="public-read")
    status, body = _api("POST /analyze", {"desired": desired, "actual": actual, "resource_type": "s3_bucket"})
    assert status == 200
    assert body["changed_attributes"] == ["acl"]
    assert body["explanation"]["predicted_label"] == "Critical"


@pytest.mark.parametrize("body", [
    "not json",
    [1, 2],
    {"desired": {}, "actual": "x", "resource_type": "s3_bucket"},
    {"desired": {}, "actual": {}, "resource_type": "rds"},
    {"desired": {}, "actual": {}, "resource_type": "s3_bucket", "drift_frequency": -1},
    {"desired": {}, "actual": {}, "resource_type": "s3_bucket", "drift_frequency": "many"},
])
def test_api_analyze_input_validation(aws, body):
    assert _api("POST /analyze", body)[0] == 400


def test_api_analyze_unknown_attribute_is_reported_not_guessed(aws):
    status, body = _api("POST /analyze", {"desired": {"x": 1}, "actual": {"x": 2}, "resource_type": "s3_bucket"})
    assert status == 200
    assert body["status"] == "unclassified_attribute" and body["explanation"] is None


def test_api_unknown_route(aws):
    assert _api("DELETE /drifts")[0] == 404


def test_api_scan_invokes_detector():
    client = boto3.client("lambda", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(client) as stub:
        stub.add_response("invoke", {"StatusCode": 200, "Payload": io.BytesIO(b'{"scanned": 3, "records": []}')},
                          {"FunctionName": "detector", "InvocationType": "RequestResponse",
                           "Payload": json.dumps({"trigger": "api"}).encode()})
        resp = lambda_api.run_scan_now(client, "detector")
    assert resp["statusCode"] == 200 and json.loads(resp["body"])["scanned"] == 3


def test_api_scan_reports_detector_failure():
    client = boto3.client("lambda", region_name=REGION, aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(client) as stub:
        stub.add_response("invoke", {"StatusCode": 200, "FunctionError": "Unhandled",
                                     "Payload": io.BytesIO(b'{"errorMessage": "boom"}')})
        resp = lambda_api.run_scan_now(client, "detector")
    assert resp["statusCode"] == 502
