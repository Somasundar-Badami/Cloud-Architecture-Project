"""
tests/test_lambda_detector.py

End-to-end tests for the AWS Lambda layer, run against moto's in-memory
AWS (no account, no network, no cost):

  - pure-Python Random Forest == scikit-learn on all 711 records
  - SG / IAM normalizers produce exactly the desired-state shape that
    terraform/monitored.tf renders (so a fresh deploy reports NO drift)
  - injected drift -> correct risk, DynamoDB finding, SNS alert,
    CloudWatch metric, drift_frequency from history, auto-remediation
  - API handler routes
"""

import json
import os
import re
from types import SimpleNamespace

import boto3
import joblib
import pytest
from moto import mock_aws

import project_paths
from rf_predict import RandomForestJSON

REGION = "us-east-1"
ACCOUNT = "123456789012"  # moto's default account id
INTERNAL = "10.0.0.0/8"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


# ---------------------------------------------------------------------------
# Model export parity
# ---------------------------------------------------------------------------

def test_exported_model_matches_sklearn_on_every_record():
    from ml_pipeline import load_dataset, separate_features_target_metadata

    df = load_dataset()
    X, _, _ = separate_features_target_metadata(df)
    pre = joblib.load(os.path.join(project_paths.MODELS_DIR, "preprocessor.joblib"))
    rf = joblib.load(os.path.join(project_paths.MODELS_DIR, "random_forest_model.joblib"))
    expected = rf.predict_proba(pre.transform(X))
    model = RandomForestJSON.load()

    for i, row in enumerate(X.to_dict("records")):
        proba = model.predict_proba(row)
        for j, label in enumerate(model.classes):
            assert proba[label] == pytest.approx(expected[i][j], abs=1e-6)


def test_exported_model_feature_layout_matches_preprocessor():
    pre = joblib.load(os.path.join(project_paths.MODELS_DIR, "preprocessor.joblib"))
    model = RandomForestJSON.load()
    assert model.feature_names == list(pre.get_feature_names_out())
    assert len(model.transform({
        "security_sensitivity": "High", "change_magnitude": "High", "port_exposure": "none",
        "resource_type": "s3_bucket", "changed_attribute": "never-seen", "public_exposure": True,
        "encryption_change": False, "privilege_change": False, "drift_frequency": 1,
    })) == len(model.feature_names)


def test_unknown_ordinal_value_is_rejected():
    model = RandomForestJSON.load()
    with pytest.raises(ValueError):
        model.transform({"security_sensitivity": "Extreme"})


# ---------------------------------------------------------------------------
# Test stack (mirrors terraform/monitored.tf)
# ---------------------------------------------------------------------------

def _monitored_tf():
    with open(os.path.join(project_paths.TERRAFORM_DIR, "monitored.tf")) as f:
        return f.read()


def build_stack():
    s3 = boto3.client("s3", region_name=REGION)
    ec2 = boto3.client("ec2", region_name=REGION)
    iam = boto3.client("iam", region_name=REGION)
    ddb = boto3.client("dynamodb", region_name=REGION)
    sns = boto3.client("sns", region_name=REGION)
    sqs = boto3.client("sqs", region_name=REGION)

    bucket = "drift-demo-sandbox-test0001"
    s3.create_bucket(Bucket=bucket)
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})

    vpc = ec2.describe_vpcs(Filters=[{"Name": "isDefault", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    sg = ec2.create_security_group(GroupName="drift-demo-sandbox-web-sg", Description="d", VpcId=vpc)["GroupId"]
    ec2.revoke_security_group_egress(GroupId=sg, IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
    ec2.authorize_security_group_egress(GroupId=sg, IpPermissions=[{"IpProtocol": "-1", "IpRanges": [{"CidrIp": INTERNAL}]}])
    ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": p, "ToPort": p, "IpRanges": [{"CidrIp": c}]}
        for p, c in ((22, INTERNAL), (3389, INTERNAL), (443, "0.0.0.0/0"), (5432, INTERNAL))])

    boundary = iam.create_policy(PolicyName="drift-demo-sandbox-boundary", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"],
                                                "Resource": [f"arn:aws:s3:::{bucket}/*"]}]}))["Policy"]["Arn"]
    role = "drift-demo-sandbox-app-role"
    iam.create_role(RoleName=role, PermissionsBoundary=boundary, AssumeRolePolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Action": "sts:AssumeRole",
            "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"},
            "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}}]}))
    iam.put_role_policy(RoleName=role, PolicyName="app-read-only", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"],
                                                "Resource": [f"arn:aws:s3:::{bucket}/*"]}]}))

    ddb.create_table(TableName="findings", BillingMode="PAY_PER_REQUEST",
                     KeySchema=[{"AttributeName": "resource_id", "KeyType": "HASH"},
                                {"AttributeName": "detected_at", "KeyType": "RANGE"}],
                     AttributeDefinitions=[{"AttributeName": "resource_id", "AttributeType": "S"},
                                           {"AttributeName": "detected_at", "AttributeType": "S"}])
    topic = sns.create_topic(Name="alerts")["TopicArn"]
    queue_url = sqs.create_queue(QueueName="alerts-inbox")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=queue_arn)

    # Exactly the structure terraform/monitored.tf renders into DESIRED_STATE_JSON.
    desired = [
        {"resource_id": bucket, "resource_type": "s3_bucket", "desired": {
            "resource_type": "aws_s3_bucket", "bucket_name": bucket, "block_public_access": True,
            "acl": "private", "encryption": {"enabled": True, "kms_key_id": None},
            "versioning": "disabled", "logging": "disabled", "lifecycle_rule": None,
            "bucket_policy_principal": f"arn:aws:iam::{ACCOUNT}:root"}},
        {"resource_id": sg, "resource_type": "security_group", "desired": {
            "resource_type": "aws_security_group", "sg_id": sg, "instance_name": "drift-demo-sandbox-web-sg",
            "inbound_ssh": {"port": 22, "source_cidr": INTERNAL},
            "inbound_rdp": {"port": 3389, "source_cidr": INTERNAL},
            "inbound_https": {"port": 443, "source_cidr": "0.0.0.0/0"},
            "inbound_custom": None,
            "outbound_default": {"port": "all", "destination_cidr": INTERNAL},
            "internal_service_port": {"port": 5432, "range": "single"},
            "peer_sg_reference": None}},
        {"resource_id": role, "resource_type": "iam_policy", "desired": {
            "resource_type": "aws_iam_entity", "entity_name": role, "actions": ["s3:GetObject"],
            "resources": [f"arn:aws:s3:::{bucket}/*"], "effect": "Allow", "requires_mfa": True,
            "trust_principal": f"arn:aws:iam::{ACCOUNT}:root", "permissions_boundary": boundary,
            "group_membership": None}},
    ]
    return SimpleNamespace(bucket=bucket, sg=sg, role=role, topic=topic, queue_url=queue_url, desired=desired)


def _set_env(monkeypatch, stack, auto_remediate=False):
    monkeypatch.setenv("DESIRED_STATE_JSON", json.dumps(stack.desired))
    monkeypatch.setenv("FINDINGS_TABLE", "findings")
    monkeypatch.setenv("ALERT_TOPIC_ARN", stack.topic)
    monkeypatch.setenv("ALERT_MIN_RISK", "High")
    monkeypatch.setenv("AUTO_REMEDIATE", "true" if auto_remediate else "false")
    monkeypatch.setenv("DETECTOR_FUNCTION_NAME", "detector")


CTX = SimpleNamespace(invoked_function_arn=f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:detector")


def _alerts(stack):
    msgs = boto3.client("sqs", region_name=REGION).receive_message(QueueUrl=stack.queue_url, MaxNumberOfMessages=10)
    return [json.loads(m["Body"]) for m in msgs.get("Messages", [])]


def _by_id(summary):
    return {r["resource_id"]: r for r in summary["results"]}


def test_desired_state_keys_match_terraform_monitored_tf():
    """Guards against monitored.tf and the normalizers drifting apart."""
    tf = _monitored_tf()
    for key in ("inbound_ssh", "inbound_rdp", "inbound_https", "inbound_custom", "outbound_default",
                "internal_service_port", "peer_sg_reference", "trust_principal", "requires_mfa",
                "permissions_boundary", "group_membership", "block_public_access", "bucket_policy_principal"):
        assert re.search(rf"\b{key}\s*=", tf), key


@mock_aws
def test_fresh_deployment_reports_no_drift(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    summary = detector_handler.lambda_handler({}, CTX)

    results = _by_id(summary)
    assert len(results) == 3
    for r in results.values():
        assert "error" not in r, r
        assert r["has_drift"] is False
        assert r["risk_label"] == "Low"
    assert _alerts(stack) == []


@mock_aws
def test_ssh_opened_to_internet_is_critical_and_alerts(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    boto3.client("ec2", region_name=REGION).authorize_security_group_ingress(
        GroupId=stack.sg, IpPermissions=[{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                                          "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])

    result = _by_id(detector_handler.lambda_handler({}, CTX))[stack.sg]
    assert result["has_drift"] is True
    assert result["risk_label"] == "Critical"

    alerts = _alerts(stack)
    assert len(alerts) == 1
    assert "inbound_ssh.source_cidr" in alerts[0]["Message"]
    assert alerts[0]["Subject"].startswith("[Critical]")

    items = boto3.resource("dynamodb", region_name=REGION).Table("findings").scan()["Items"]
    sg_items = [i for i in items if i["resource_id"] == stack.sg]
    assert sg_items[0]["risk_label"] == "Critical"
    assert sg_items[0]["features"]["port_exposure"] == "0.0.0.0/0"


@mock_aws
def test_s3_public_access_block_disabled_is_critical_and_auto_remediated(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack, auto_remediate=True)
    s3 = boto3.client("s3", region_name=REGION)
    s3.put_public_access_block(Bucket=stack.bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": False, "IgnorePublicAcls": False, "BlockPublicPolicy": False, "RestrictPublicBuckets": False})

    result = _by_id(detector_handler.lambda_handler({}, CTX))[stack.bucket]
    assert result["risk_label"] == "Critical"
    assert result["remediation"] == ["s3:re-enabled block_public_access"]
    cfg = s3.get_public_access_block(Bucket=stack.bucket)["PublicAccessBlockConfiguration"]
    assert all(cfg.values())

    # Next scan: fixed, so no drift.
    assert _by_id(detector_handler.lambda_handler({}, CTX))[stack.bucket]["has_drift"] is False


@mock_aws
def test_auto_remediation_revokes_public_ssh(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack, auto_remediate=True)
    ec2 = boto3.client("ec2", region_name=REGION)
    ec2.authorize_security_group_ingress(GroupId=stack.sg, IpPermissions=[
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])

    result = _by_id(detector_handler.lambda_handler({}, CTX))[stack.sg]
    assert result["remediation"] == ["ec2:revoked 0.0.0.0/0 on port 22"]
    assert _by_id(detector_handler.lambda_handler({}, CTX))[stack.sg]["has_drift"] is False


@mock_aws
def test_iam_wildcard_escalation_is_critical(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    boto3.client("iam", region_name=REGION).put_role_policy(
        RoleName=stack.role, PolicyName="app-read-only", PolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}))

    result = _by_id(detector_handler.lambda_handler({}, CTX))[stack.role]
    assert result["has_drift"] is True
    assert result["risk_label"] == "Critical"


@mock_aws
def test_mfa_removed_is_high(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    boto3.client("iam", region_name=REGION).update_assume_role_policy(
        RoleName=stack.role, PolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"AWS": f"arn:aws:iam::{ACCOUNT}:root"}}]}))

    assert _by_id(detector_handler.lambda_handler({}, CTX))[stack.role]["risk_label"] == "High"


@mock_aws
def test_versioning_enabled_outside_terraform_is_low_risk_no_alert(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    boto3.client("s3", region_name=REGION).put_bucket_versioning(
        Bucket=stack.bucket, VersioningConfiguration={"Status": "Enabled"})

    result = _by_id(detector_handler.lambda_handler({}, CTX))[stack.bucket]
    assert result["has_drift"] is True
    assert result["risk_label"] in ("Low", "Medium")
    assert _alerts(stack) == []


@mock_aws
def test_drift_frequency_counts_previous_drift_findings(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    boto3.client("ec2", region_name=REGION).authorize_security_group_ingress(
        GroupId=stack.sg, IpPermissions=[{"IpProtocol": "tcp", "FromPort": 3389, "ToPort": 3389,
                                          "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
    for _ in range(3):
        detector_handler.lambda_handler({}, CTX)

    items = boto3.resource("dynamodb", region_name=REGION).Table("findings").scan()["Items"]
    freqs = sorted(int(i["features"]["drift_frequency"]) for i in items if i["resource_id"] == stack.sg)
    assert freqs == [0, 1, 2]


@mock_aws
def test_deleted_rule_is_flagged_for_review_not_guessed(monkeypatch):
    import detector_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    boto3.client("ec2", region_name=REGION).revoke_security_group_ingress(
        GroupId=stack.sg, IpPermissions=[{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                                          "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])

    result = _by_id(detector_handler.lambda_handler({}, CTX))[stack.sg]
    assert result["has_drift"] is True
    assert result["risk_label"] == "Review"
    assert len(_alerts(stack)) == 1


@mock_aws
def test_missing_resource_is_reported_without_stopping_scan(monkeypatch):
    import detector_handler

    stack = build_stack()
    stack.desired[0]["resource_id"] = "bucket-that-does-not-exist"
    _set_env(monkeypatch, stack)
    results = _by_id(detector_handler.lambda_handler({}, CTX))
    assert "error" in results["bucket-that-does-not-exist"]
    assert results[stack.sg]["has_drift"] is False


# ---------------------------------------------------------------------------
# API handler
# ---------------------------------------------------------------------------

def _api_event(route, resource=None):
    return {"routeKey": route, "pathParameters": {"resource": resource} if resource else {},
            "requestContext": {"authorizer": {"jwt": {"claims": {"email": "admin@example.com"}}}}}


@mock_aws
def test_api_returns_latest_findings_and_history(monkeypatch):
    import detector_handler
    import api_handler

    stack = build_stack()
    _set_env(monkeypatch, stack)
    detector_handler.lambda_handler({}, CTX)
    detector_handler.lambda_handler({}, CTX)

    resp = api_handler.lambda_handler(_api_event("GET /findings"), None)
    assert resp["statusCode"] == 200
    assert len(json.loads(resp["body"])["findings"]) == 3

    resp = api_handler.lambda_handler(_api_event("GET /findings/{resource}", stack.sg), None)
    assert len(json.loads(resp["body"])["history"]) == 2

    resp = api_handler.lambda_handler(_api_event("GET /findings/{resource}", "not-monitored"), None)
    assert resp["statusCode"] == 404


def test_api_unknown_route_is_404(monkeypatch):
    import api_handler

    monkeypatch.setenv("DESIRED_STATE_JSON", "[]")
    monkeypatch.setenv("FINDINGS_TABLE", "findings")
    resp = api_handler.lambda_handler(_api_event("DELETE /everything"), None)
    assert resp["statusCode"] == 404


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_should_alert_thresholds():
    from detector_handler import should_alert

    assert should_alert("Critical", "High")
    assert should_alert("High", "High")
    assert not should_alert("Medium", "High")
    assert should_alert("Review", "Critical")
