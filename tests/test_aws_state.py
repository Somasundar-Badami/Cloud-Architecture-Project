"""
tests/test_aws_state.py

Tests for src/aws_state.py and src/aws_normalizer.py.

IMPORTANT -- how mocked vs. real tests are distinguished in this file:

  * Every test EXCEPT the one in the "REAL AWS INTEGRATION TEST" section
    at the bottom uses either hand-crafted raw-response dicts (for
    aws_normalizer.py, which does pure data transformation and needs no
    AWS connection at all) or botocore's official `Stubber` (for
    aws_state.py, which makes real boto3 client calls that Stubber
    intercepts and answers with a scripted, realistic payload -- no
    network call ever leaves the process). These are ALL unit tests:
    fast, deterministic, runnable with zero AWS credentials or network
    access, and they run as part of the normal test suite every time.

  * The single test in `TestRealAWSIntegration` at the bottom is the ONLY
    test in this file that makes an actual, unstubbed boto3 call to real
    AWS. It is skipped by default and only runs if BOTH environment
    variables RUN_REAL_AWS_TESTS=1 and AWS_TEST_BUCKET=<a real bucket
    name> are set, since it requires real, working AWS credentials and
    network access to AWS -- neither of which exists in this project's
    own sandboxed development environment (see README for the actual
    observed failure mode when this was attempted here).
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402
from botocore.stub import Stubber  # noqa: E402
import botocore.exceptions  # noqa: E402

from aws_state import (  # noqa: E402
    check_aws_credentials,
    get_s3_client,
    fetch_s3_bucket_raw_config,
    AWSConfigurationError,
    CATEGORY_NO_CREDENTIALS,
    CATEGORY_NETWORK_UNREACHABLE,
    CATEGORY_ACCESS_DENIED,
    CATEGORY_NOT_FOUND,
)
from aws_normalizer import (  # noqa: E402
    normalize_s3_actual_state,
    derive_s3_desired_state_from_terraform,
    load_terraform_resources,
    _public_access_block_to_bool,
    _acl_response_to_string,
    _encryption_to_dict,
    _versioning_to_string,
    _logging_to_string,
    _lifecycle_to_dict,
    _policy_to_principal_string,
)
from drift_engine import detect_drift  # noqa: E402

import project_paths  # noqa: E402
TERRAFORM_DIR = project_paths.TERRAFORM_DIR
TEST_BUCKET = "drift-demo-sandbox-testfixture01"


# ===========================================================================
# 1. Unit tests: AWS response normalization (mocked/hand-crafted responses)
# ===========================================================================

class TestPublicAccessBlockNormalization:
    def test_all_four_settings_true_is_blocked(self):
        pab = {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}
        assert _public_access_block_to_bool(pab) is True

    def test_one_setting_false_is_not_fully_blocked(self):
        pab = {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": False, "RestrictPublicBuckets": True}
        assert _public_access_block_to_bool(pab) is False

    def test_none_pab_is_not_blocked(self):
        """No PublicAccessBlockConfiguration at all (AWS's NoSuch... case)
        means nothing is blocked -- must map to False, not error."""
        assert _public_access_block_to_bool(None) is False


class TestAclNormalization:
    def test_private_acl_no_public_grants(self):
        acl_response = {
            "Owner": {"ID": "abc"},
            "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"}],
        }
        assert _acl_response_to_string(acl_response) == "private"

    def test_public_read_grant_detected(self):
        acl_response = {
            "Owner": {"ID": "abc"},
            "Grants": [
                {"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"},
                {"Grantee": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AllUsers"}, "Permission": "READ"},
            ],
        }
        assert _acl_response_to_string(acl_response) == "public-read"

    def test_authenticated_users_group_is_not_treated_as_public(self):
        """Only the AllUsers group counts as 'public' in this project's
        simplified schema -- AuthenticatedUsers is a documented, deliberate
        simplification, not a bug."""
        acl_response = {
            "Owner": {"ID": "abc"},
            "Grants": [{"Grantee": {"Type": "Group", "URI": "http://acs.amazonaws.com/groups/global/AuthenticatedUsers"}, "Permission": "READ"}],
        }
        assert _acl_response_to_string(acl_response) == "private"


class TestEncryptionNormalization:
    def test_no_encryption_config_is_disabled(self):
        assert _encryption_to_dict(None) == {"enabled": False, "kms_key_id": None}

    def test_aes256_encryption_enabled_no_kms_key(self):
        config = {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}
        assert _encryption_to_dict(config) == {"enabled": True, "kms_key_id": None}

    def test_kms_encryption_captures_key_id(self):
        config = {"Rules": [{"ApplyServerSideEncryptionByDefault": {
            "SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "arn:aws:kms:us-east-1:123456789012:key/abc"
        }}]}
        result = _encryption_to_dict(config)
        assert result["enabled"] is True
        assert result["kms_key_id"] == "arn:aws:kms:us-east-1:123456789012:key/abc"


class TestVersioningLoggingNormalization:
    def test_versioning_enabled(self):
        assert _versioning_to_string({"Status": "Enabled"}) == "enabled"

    def test_versioning_never_configured_is_disabled(self):
        """A bucket that never had versioning touched returns {} with no
        Status key at all -- must map to 'disabled', not crash."""
        assert _versioning_to_string({}) == "disabled"

    def test_versioning_suspended_is_disabled(self):
        assert _versioning_to_string({"Status": "Suspended"}) == "disabled"

    def test_logging_enabled_detected(self):
        assert _logging_to_string({"LoggingEnabled": {"TargetBucket": "logs", "TargetPrefix": "x/"}}) == "enabled"

    def test_logging_never_configured_is_disabled(self):
        assert _logging_to_string({}) == "disabled"


class TestLifecycleNormalization:
    def test_no_lifecycle_rules_is_none(self):
        assert _lifecycle_to_dict(None) is None
        assert _lifecycle_to_dict([]) is None

    def test_lifecycle_rule_present(self):
        rules = [{"Status": "Enabled", "Expiration": {"Days": 365}}]
        assert _lifecycle_to_dict(rules) == {"enabled": True, "retention_days": 365}


class TestPolicyPrincipalNormalization:
    def test_no_policy_returns_owner_placeholder(self):
        result = _policy_to_principal_string(None, "123456789012", "my-bucket")
        assert result == "arn:aws:iam::123456789012:root"

    def test_wildcard_string_principal_detected(self):
        policy = {"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject"}]}
        assert _policy_to_principal_string(policy, "123456789012", "my-bucket") == "*"

    def test_wildcard_aws_principal_dict_detected(self):
        policy = {"Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "s3:GetObject"}]}
        assert _policy_to_principal_string(policy, "123456789012", "my-bucket") == "*"

    def test_specific_principal_not_treated_as_wildcard(self):
        policy = {"Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::999999999999:root"}, "Action": "s3:GetObject"}]}
        result = _policy_to_principal_string(policy, "123456789012", "my-bucket")
        assert result != "*"


class TestNormalizeS3ActualStateFullPipeline:
    """Tests the full normalize_s3_actual_state() using a complete,
    hand-crafted (but realistic) raw boto3 response bundle -- a mocked
    unit test, no AWS connection involved."""

    def _matching_raw_bundle(self):
        return {
            "bucket_name": TEST_BUCKET,
            "public_access_block": {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True},
            "acl": {"Owner": {"ID": "abc"}, "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"}]},
            "encryption": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "versioning": {},
            "logging": {},
            "lifecycle": None,
            "policy": None,
        }

    def test_normalize_produces_all_required_schema_keys(self):
        result = normalize_s3_actual_state(self._matching_raw_bundle(), account_id="123456789012")
        expected_keys = {
            "resource_type", "bucket_name", "block_public_access", "acl",
            "encryption", "versioning", "logging", "lifecycle_rule", "bucket_policy_principal",
        }
        assert set(result.keys()) == expected_keys

    def test_normalize_resource_type_is_correct(self):
        result = normalize_s3_actual_state(self._matching_raw_bundle())
        assert result["resource_type"] == "aws_s3_bucket"

    def test_normalize_encryption_is_nested_dict(self):
        result = normalize_s3_actual_state(self._matching_raw_bundle())
        assert result["encryption"] == {"enabled": True, "kms_key_id": None}


class TestMalformedAWSResponses:
    """
    Confirms behavior against MALFORMED/incomplete AWS responses -- shapes
    that shouldn't normally come from a well-behaved AWS API, but which
    the code must not silently mishandle if they ever do (a botocore
    version skew, a partial API response, etc.).

    Two distinct, deliberately different behaviors are verified:
      (a) missing OPTIONAL sub-fields within an otherwise-present response
          (e.g. a Grant missing "Grantee") must be handled gracefully via
          .get()-with-default, matching real-world AWS response variance.
      (b) a missing REQUIRED top-level key (e.g. no "acl" entry at all in
          the raw bundle) must fail LOUDLY with a clear KeyError, not
          silently produce a wrong/default normalized value -- the same
          fail-loud philosophy feature_extraction.py already uses for
          unknown attributes.
    """

    def test_missing_required_top_level_key_raises_keyerror(self):
        malformed = {
            "bucket_name": TEST_BUCKET,
            "public_access_block": None,
            # "acl" key entirely absent -- malformed/incomplete bundle
            "encryption": None,
            "versioning": {},
            "logging": {},
            "lifecycle": None,
            "policy": None,
        }
        with pytest.raises(KeyError):
            normalize_s3_actual_state(malformed)

    def test_missing_bucket_name_raises_keyerror(self):
        malformed = {
            "public_access_block": None, "acl": {"Grants": []}, "encryption": None,
            "versioning": {}, "logging": {}, "lifecycle": None, "policy": None,
        }
        with pytest.raises(KeyError):
            normalize_s3_actual_state(malformed)

    def test_acl_grant_missing_grantee_handled_gracefully(self):
        """A malformed Grant missing its 'Grantee' sub-key entirely must
        not crash -- treated as non-public rather than erroring, since
        .get('Grantee', {}) safely defaults."""
        acl_response = {"Owner": {"ID": "abc"}, "Grants": [{"Permission": "READ"}]}
        assert _acl_response_to_string(acl_response) == "private"

    def test_acl_response_missing_grants_key_entirely(self):
        acl_response = {"Owner": {"ID": "abc"}}  # no "Grants" key at all
        assert _acl_response_to_string(acl_response) == "private"

    def test_encryption_rule_missing_apply_default_subkey(self):
        """A malformed encryption rule missing
        'ApplyServerSideEncryptionByDefault' entirely -- still counts as
        'a rule exists' (enabled=True) since AWS only returns Rules at
        all when encryption is configured; kms_key_id gracefully None."""
        config = {"Rules": [{}]}
        result = _encryption_to_dict(config)
        assert result["enabled"] is True
        assert result["kms_key_id"] is None

    def test_lifecycle_rule_missing_expiration_subkey(self):
        rules = [{"Status": "Enabled"}]  # no "Expiration" key at all
        result = _lifecycle_to_dict(rules)
        assert result == {"enabled": True, "retention_days": None}

    def test_policy_statement_missing_principal_key(self):
        """A malformed policy statement missing 'Principal' entirely must
        not crash -- treated as non-wildcard (falls through to owner
        placeholder) rather than erroring."""
        policy = {"Statement": [{"Effect": "Allow", "Action": "s3:GetObject"}]}
        result = _policy_to_principal_string(policy, "123456789012", TEST_BUCKET)
        assert result == "arn:aws:iam::123456789012:root"

    def test_policy_missing_statement_key_entirely(self):
        policy = {}  # malformed: no "Statement" key
        result = _policy_to_principal_string(policy, "123456789012", TEST_BUCKET)
        assert result == "arn:aws:iam::123456789012:root"

    def test_fetch_raw_config_with_stubber_returning_empty_acl_grants(self):
        """End-to-end: a syntactically valid but minimally-populated (as
        real AWS can genuinely return for a brand-new bucket with no
        explicit grants beyond the owner) ACL response flows through
        fetch -> normalize without error."""
        client = get_s3_client(region_name="us-east-1")
        stubber = Stubber(client)
        stubber.add_response("head_bucket", {}, {"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_public_access_block", service_error_code="NoSuchPublicAccessBlockConfiguration", expected_params={"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_acl", {"Owner": {"ID": "abc"}, "Grants": []}, {"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_bucket_encryption", service_error_code="ServerSideEncryptionConfigurationNotFoundError", expected_params={"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_versioning", {}, {"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_logging", {}, {"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_bucket_lifecycle_configuration", service_error_code="NoSuchLifecycleConfiguration", expected_params={"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_bucket_policy", service_error_code="NoSuchBucketPolicy", expected_params={"Bucket": TEST_BUCKET})

        with stubber:
            raw = fetch_s3_bucket_raw_config(client, TEST_BUCKET)
        normalized = normalize_s3_actual_state(raw, account_id="000000000000")
        assert normalized["acl"] == "private"
        assert normalized["block_public_access"] is False


# ===========================================================================
# 2. Unit tests: desired-state normalization (Terraform -> schema)
# ===========================================================================

class TestDesiredStateFromTerraform:
    def test_load_terraform_resources_parses_real_tf_files(self):
        resources = load_terraform_resources(TERRAFORM_DIR)
        assert "aws_s3_bucket_public_access_block.demo" in resources
        assert "aws_s3_bucket_server_side_encryption_configuration.demo" in resources
        assert "aws_s3_bucket_versioning.demo" in resources
        assert "aws_s3_bucket_acl.demo" in resources

    def test_derive_desired_state_matches_actual_main_tf_declarations(self):
        """Regression-pinned to this project's REAL terraform/main.tf --
        if someone edits main.tf without updating this test, it fails
        loudly rather than silently drifting out of sync."""
        desired = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, TEST_BUCKET)
        assert desired["resource_type"] == "aws_s3_bucket"
        assert desired["bucket_name"] == TEST_BUCKET
        assert desired["block_public_access"] is True  # all 4 PAB settings declared true
        assert desired["acl"] == "private"
        assert desired["encryption"] == {"enabled": True, "kms_key_id": None}  # AES256, no KMS key
        assert desired["versioning"] == "disabled"  # explicitly declared Disabled
        assert desired["logging"] == "disabled"  # no logging resource declared
        assert desired["lifecycle_rule"] is None  # no lifecycle resource declared
        assert desired["bucket_policy_principal"] != "*"  # no policy resource declared

    def test_derive_desired_state_is_deterministic(self):
        d1 = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, TEST_BUCKET)
        d2 = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, TEST_BUCKET)
        assert d1 == d2

    def test_derive_desired_state_uses_the_supplied_bucket_name(self):
        desired = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, "some-other-bucket-name")
        assert desired["bucket_name"] == "some-other-bucket-name"


# ===========================================================================
# 3. Unit tests: the adapter combined with detect_drift()
# ===========================================================================

class TestAdapterWithDetectDrift:
    def test_matching_actual_state_produces_no_drift(self):
        desired = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, TEST_BUCKET)
        raw_matching = {
            "bucket_name": TEST_BUCKET,
            "public_access_block": {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True},
            "acl": {"Owner": {"ID": "abc"}, "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"}]},
            "encryption": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "versioning": {},
            "logging": {},
            "lifecycle": None,
            "policy": None,
        }
        actual = normalize_s3_actual_state(raw_matching, account_id="000000000000")
        drift = detect_drift(desired, actual)
        assert drift["has_drift"] is False
        assert drift["num_changes"] == 0

    def test_public_access_block_disabled_outside_terraform_is_detected_as_drift(self):
        """The genuine drift scenario this milestone asks for: ONE
        supported configuration changed outside Terraform."""
        desired = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, TEST_BUCKET)
        raw_drifted = {
            "bucket_name": TEST_BUCKET,
            "public_access_block": None,  # PAB removed outside Terraform
            "acl": {"Owner": {"ID": "abc"}, "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"}]},
            "encryption": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "versioning": {},
            "logging": {},
            "lifecycle": None,
            "policy": None,
        }
        actual = normalize_s3_actual_state(raw_drifted, account_id="000000000000")
        drift = detect_drift(desired, actual)
        assert drift["has_drift"] is True
        assert drift["num_changes"] == 1
        assert drift["changed_attributes"] == ["block_public_access"]
        assert drift["changes"][0]["old_value"] is True
        assert drift["changes"][0]["new_value"] is False

    def test_drift_result_feeds_into_existing_feature_extraction_unmodified(self):
        """Confirms the adapter's output is fully compatible with
        feature_extraction.py exactly as it already exists -- no adapter-
        side patching of feature_extraction required."""
        from feature_extraction import extract_features

        desired = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, TEST_BUCKET)
        raw_drifted = {
            "bucket_name": TEST_BUCKET,
            "public_access_block": None,
            "acl": {"Owner": {"ID": "abc"}, "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"}]},
            "encryption": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
            "versioning": {},
            "logging": {},
            "lifecycle": None,
            "policy": None,
        }
        actual = normalize_s3_actual_state(raw_drifted, account_id="000000000000")
        drift = detect_drift(desired, actual)
        features = extract_features("s3_bucket", drift, drift_frequency=0)

        assert features["public_exposure"] is True
        assert features["security_sensitivity"] == "High"
        assert features["change_magnitude"] == "High"
        assert features["changed_attribute"] == "block_public_access"


# ===========================================================================
# 4. Unit tests: missing/invalid AWS configuration handling (via Stubber)
# ===========================================================================

class TestFetchS3BucketRawConfigWithStubber:
    """Uses botocore's official Stubber to intercept real boto3 client
    calls with scripted responses -- no network call ever leaves the
    process. This is the standard, officially-supported way to unit-test
    boto3-calling code."""

    def test_successful_fetch_with_all_settings_configured(self):
        client = get_s3_client(region_name="us-east-1")
        stubber = Stubber(client)
        stubber.add_response("head_bucket", {}, {"Bucket": TEST_BUCKET})
        stubber.add_response(
            "get_public_access_block",
            {"PublicAccessBlockConfiguration": {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}},
            {"Bucket": TEST_BUCKET},
        )
        stubber.add_response(
            "get_bucket_acl",
            {"Owner": {"ID": "abc"}, "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "abc"}, "Permission": "FULL_CONTROL"}]},
            {"Bucket": TEST_BUCKET},
        )
        stubber.add_response(
            "get_bucket_encryption",
            {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}},
            {"Bucket": TEST_BUCKET},
        )
        stubber.add_response("get_bucket_versioning", {"Status": "Enabled"}, {"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_logging", {}, {"Bucket": TEST_BUCKET})
        stubber.add_response(
            "get_bucket_lifecycle_configuration",
            {"Rules": [{"Status": "Enabled", "Expiration": {"Days": 90}}]},
            {"Bucket": TEST_BUCKET},
        )
        stubber.add_response(
            "get_bucket_policy",
            {"Policy": json.dumps({"Statement": [{"Effect": "Allow", "Principal": "*", "Action": "s3:GetObject"}]})},
            {"Bucket": TEST_BUCKET},
        )

        with stubber:
            raw = fetch_s3_bucket_raw_config(client, TEST_BUCKET)

        assert raw["bucket_name"] == TEST_BUCKET
        assert raw["public_access_block"]["BlockPublicAcls"] is True
        assert raw["lifecycle"] == [{"Status": "Enabled", "Expiration": {"Days": 90}}]
        assert raw["policy"]["Statement"][0]["Principal"] == "*"

    def test_not_configured_states_become_none_not_errors(self):
        """The 'nothing configured' path -- every optional S3 setting
        absent -- must all resolve to None, not raise."""
        client = get_s3_client(region_name="us-east-1")
        stubber = Stubber(client)
        stubber.add_response("head_bucket", {}, {"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_public_access_block", service_error_code="NoSuchPublicAccessBlockConfiguration", expected_params={"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_acl", {"Owner": {"ID": "x"}, "Grants": []}, {"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_bucket_encryption", service_error_code="ServerSideEncryptionConfigurationNotFoundError", expected_params={"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_versioning", {}, {"Bucket": TEST_BUCKET})
        stubber.add_response("get_bucket_logging", {}, {"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_bucket_lifecycle_configuration", service_error_code="NoSuchLifecycleConfiguration", expected_params={"Bucket": TEST_BUCKET})
        stubber.add_client_error("get_bucket_policy", service_error_code="NoSuchBucketPolicy", expected_params={"Bucket": TEST_BUCKET})

        with stubber:
            raw = fetch_s3_bucket_raw_config(client, TEST_BUCKET)

        assert raw["public_access_block"] is None
        assert raw["encryption"] is None
        assert raw["lifecycle"] is None
        assert raw["policy"] is None

    def test_bucket_not_found_raises_categorized_error(self):
        client = get_s3_client(region_name="us-east-1")
        stubber = Stubber(client)
        stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404, expected_params={"Bucket": TEST_BUCKET})

        with stubber:
            with pytest.raises(AWSConfigurationError) as exc_info:
                fetch_s3_bucket_raw_config(client, TEST_BUCKET)

        assert exc_info.value.category == CATEGORY_NOT_FOUND

    def test_access_denied_raises_categorized_error(self):
        client = get_s3_client(region_name="us-east-1")
        stubber = Stubber(client)
        stubber.add_client_error("head_bucket", service_error_code="403", http_status_code=403, expected_params={"Bucket": TEST_BUCKET})

        with stubber:
            with pytest.raises(AWSConfigurationError) as exc_info:
                fetch_s3_bucket_raw_config(client, TEST_BUCKET)

        assert exc_info.value.category == CATEGORY_ACCESS_DENIED

    def test_unexpected_client_error_raises_other_category(self):
        client = get_s3_client(region_name="us-east-1")
        stubber = Stubber(client)
        stubber.add_client_error("head_bucket", service_error_code="InternalError", http_status_code=500, expected_params={"Bucket": TEST_BUCKET})

        with stubber:
            with pytest.raises(AWSConfigurationError) as exc_info:
                fetch_s3_bucket_raw_config(client, TEST_BUCKET)

        assert exc_info.value.category == "other"


class TestCheckAwsCredentials:
    """check_aws_credentials() is tested against REAL botocore exception
    types (NoCredentialsError is raised naturally by boto3/botocore itself
    when no credential provider resolves anything -- no stubbing needed
    for this particular case, since it's the actual, real behavior of this
    sandboxed environment with zero configured credentials)."""

    def test_no_credentials_configured_returns_clear_message(self, monkeypatch):
        # Ensure no credentials leak in from the test-runner's own
        # environment, so this test is reliable wherever it runs.
        for var in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"]:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/tmp/definitely_does_not_exist_credentials")
        monkeypatch.setenv("AWS_CONFIG_FILE", "/tmp/definitely_does_not_exist_config")
        # boto3 caches credentials on its module-level default session; an
        # earlier test (or a developer machine with real AWS credentials)
        # would otherwise leak them in here.
        import boto3
        monkeypatch.setattr(boto3, "DEFAULT_SESSION", None)

        ok, message, identity = check_aws_credentials()
        assert ok is False
        assert "credentials" in message.lower()
        assert identity is None

    def test_valid_credentials_via_stubbed_sts_client(self, monkeypatch):
        """Simulates the SUCCESS path by stubbing the STS client boto3
        constructs inside check_aws_credentials()."""
        import aws_state

        real_boto3_client = aws_state.boto3.client

        def fake_client(service_name, **kwargs):
            client = real_boto3_client(service_name, region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
            stubber = Stubber(client)
            stubber.add_response("get_caller_identity", {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/demo", "UserId": "AID123"})
            stubber.activate()
            client._test_stubber = stubber  # keep alive
            return client

        monkeypatch.setattr(aws_state.boto3, "client", fake_client)
        ok, message, identity = check_aws_credentials()
        assert ok is True
        assert identity["account"] == "123456789012"

    def test_client_error_during_credential_check_returns_message(self, monkeypatch):
        import aws_state

        real_boto3_client = aws_state.boto3.client

        def fake_client(service_name, **kwargs):
            client = real_boto3_client(service_name, region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
            stubber = Stubber(client)
            stubber.add_client_error("get_caller_identity", service_error_code="InvalidClientTokenId", http_status_code=403)
            stubber.activate()
            client._test_stubber = stubber
            return client

        monkeypatch.setattr(aws_state.boto3, "client", fake_client)
        ok, message, identity = check_aws_credentials()
        assert ok is False
        assert "InvalidClientTokenId" in message


# ===========================================================================
# REAL AWS INTEGRATION TEST -- skipped by default, never runs as part of
# the normal unit test suite. See module docstring for exactly why.
# ===========================================================================

class TestRealAWSIntegration:
    @pytest.mark.skipif(
        not (os.environ.get("RUN_REAL_AWS_TESTS") == "1" and os.environ.get("AWS_TEST_BUCKET")),
        reason=(
            "Real AWS integration test skipped by default. To run it against "
            "a real deployed bucket with real, working AWS credentials: "
            "RUN_REAL_AWS_TESTS=1 AWS_TEST_BUCKET=<bucket-name> pytest tests/test_aws_state.py -k real"
        ),
    )
    def test_real_bucket_fetch_and_drift_detection(self):
        bucket_name = os.environ["AWS_TEST_BUCKET"]
        ok, message, identity = check_aws_credentials()
        assert ok, f"Real AWS credentials required for this test: {message}"

        client = get_s3_client()
        raw = fetch_s3_bucket_raw_config(client, bucket_name)
        actual = normalize_s3_actual_state(raw, account_id=identity["account"])
        desired = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, bucket_name)

        drift = detect_drift(desired, actual)
        print(f"\nREAL AWS drift result for '{bucket_name}': {drift}")
        assert isinstance(drift["has_drift"], bool)
