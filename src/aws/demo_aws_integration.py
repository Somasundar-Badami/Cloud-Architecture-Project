"""
demo_aws_integration.py

End-to-end demonstration for the AWS Integration milestone (Phase 1: S3).

Sequence:
  1. Run the REAL AWS credential/connectivity check (src/aws_state.py).
     In an environment with no configured credentials and/or no network
     path to AWS, this fails -- and the script shows that REAL failure
     rather than fabricating a success.
  2. If (and only if) step 1 succeeds AND a --bucket argument is given,
     fetch the REAL bucket state from AWS via boto3 and compare it
     against the Terraform-derived desired state.
  3. Otherwise, fall back to a SIMULATED demonstration using botocore's
     official Stubber to inject realistic AWS response payloads -- this
     path is explicitly labeled as simulated everywhere it appears in the
     output, never presented as if it were live AWS data.
  4. Either way, run the (possibly simulated) drift result through the
     EXISTING, unmodified feature_extraction.extract_features() and the
     EXISTING, unmodified saved primary Random Forest model + preprocessor
     -- no retraining, no dataset changes.

Run with:
    python3 demo_aws_integration.py                  # simulated (no AWS creds needed)
    python3 demo_aws_integration.py --bucket NAME     # attempts REAL AWS first
"""

import argparse
import json
import os
import sys

import joblib
import pandas as pd
from botocore.stub import Stubber

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_paths  # noqa: E402

from aws_state import (  # noqa: E402
    check_aws_credentials,
    get_s3_client,
    fetch_s3_bucket_raw_config,
    AWSConfigurationError,
)
from aws_normalizer import (  # noqa: E402
    normalize_s3_actual_state,
    derive_s3_desired_state_from_terraform,
)
from drift_engine import detect_drift  # noqa: E402
from feature_extraction import extract_features  # noqa: E402
from ml_pipeline import FEATURE_COLUMNS, BOOLEAN_FEATURES  # noqa: E402

TERRAFORM_DIR = project_paths.TERRAFORM_DIR
MODELS_DIR = project_paths.MODELS_DIR

DEMO_BUCKET_NAME = "drift-demo-sandbox-simulated0001"


# ---------------------------------------------------------------------------
# Step 1: real credential check
# ---------------------------------------------------------------------------

def run_real_credential_check():
    print("=" * 78)
    print("STEP 1: Real AWS credential/connectivity check (src/aws_state.py)")
    print("=" * 78)
    ok, message, identity = check_aws_credentials()
    print(f"AWS credentials valid: {ok}")
    print(f"Message: {message}")
    if identity:
        print(f"Identity: {identity}")
    print()
    return ok


# ---------------------------------------------------------------------------
# Step 2 (real path): fetch actual bucket state from real AWS
# ---------------------------------------------------------------------------

def run_real_aws_path(bucket_name):
    print("=" * 78)
    print(f"STEP 2 [REAL AWS]: Fetching actual state for bucket '{bucket_name}'")
    print("=" * 78)
    client = get_s3_client()
    raw = fetch_s3_bucket_raw_config(client, bucket_name)
    print("[REAL AWS] Real raw boto3 response bundle received from live AWS.")
    actual_state = normalize_s3_actual_state(raw)
    desired_state = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, bucket_name)
    return desired_state, actual_state, "real_aws"


# ---------------------------------------------------------------------------
# Step 2 (fallback path): simulate before/after AWS responses via Stubber
# ---------------------------------------------------------------------------

def _stub_matching_responses(stubber, bucket_name):
    stubber.add_response("head_bucket", {}, {"Bucket": bucket_name})
    stubber.add_response(
        "get_public_access_block",
        {"PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        }},
        {"Bucket": bucket_name},
    )
    stubber.add_response(
        "get_bucket_acl",
        {"Owner": {"DisplayName": "demo", "ID": "demo-id"},
         "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "demo-id"}, "Permission": "FULL_CONTROL"}]},
        {"Bucket": bucket_name},
    )
    stubber.add_response(
        "get_bucket_encryption",
        {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}},
        {"Bucket": bucket_name},
    )
    stubber.add_response("get_bucket_versioning", {}, {"Bucket": bucket_name})
    stubber.add_response("get_bucket_logging", {}, {"Bucket": bucket_name})
    stubber.add_client_error(
        "get_bucket_lifecycle_configuration", service_error_code="NoSuchLifecycleConfiguration",
        expected_params={"Bucket": bucket_name},
    )
    stubber.add_client_error(
        "get_bucket_policy", service_error_code="NoSuchBucketPolicy",
        expected_params={"Bucket": bucket_name},
    )


def _stub_drifted_responses(stubber, bucket_name):
    """Same as matching, EXCEPT public access block has been disabled
    outside Terraform -- the ONE genuine configuration change for this
    demonstration (requirement 8)."""
    stubber.add_response("head_bucket", {}, {"Bucket": bucket_name})
    stubber.add_client_error(
        "get_public_access_block", service_error_code="NoSuchPublicAccessBlockConfiguration",
        expected_params={"Bucket": bucket_name},
    )
    stubber.add_response(
        "get_bucket_acl",
        {"Owner": {"DisplayName": "demo", "ID": "demo-id"},
         "Grants": [{"Grantee": {"Type": "CanonicalUser", "ID": "demo-id"}, "Permission": "FULL_CONTROL"}]},
        {"Bucket": bucket_name},
    )
    stubber.add_response(
        "get_bucket_encryption",
        {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}},
        {"Bucket": bucket_name},
    )
    stubber.add_response("get_bucket_versioning", {}, {"Bucket": bucket_name})
    stubber.add_response("get_bucket_logging", {}, {"Bucket": bucket_name})
    stubber.add_client_error(
        "get_bucket_lifecycle_configuration", service_error_code="NoSuchLifecycleConfiguration",
        expected_params={"Bucket": bucket_name},
    )
    stubber.add_client_error(
        "get_bucket_policy", service_error_code="NoSuchBucketPolicy",
        expected_params={"Bucket": bucket_name},
    )


def run_simulated_path(bucket_name, credential_check_message):
    print("=" * 78)
    print("STEP 2 [SIMULATED]: No real AWS access available in this environment")
    print("=" * 78)
    print(f"Reason: {credential_check_message}")
    print(
        "[SIMULATED] Falling back to a SIMULATED demonstration using botocore's "
        "official Stubber to inject realistic AWS API response payloads through "
        "the REAL src/aws_state.py and src/aws_normalizer.py code paths. This is "
        "clearly a simulation, not live AWS data -- labeled [SIMULATED] throughout "
        "this output and in the README."
    )
    print()

    desired_state = derive_s3_desired_state_from_terraform(TERRAFORM_DIR, bucket_name)

    print("[SIMULATED] --- BEFORE: actual state matches desired state (no drift) ---")
    client_before = get_s3_client(region_name="us-east-1")
    stubber_before = Stubber(client_before)
    _stub_matching_responses(stubber_before, bucket_name)
    with stubber_before:
        raw_before = fetch_s3_bucket_raw_config(client_before, bucket_name)
    actual_before = normalize_s3_actual_state(raw_before, account_id="000000000000")
    drift_before = detect_drift(desired_state, actual_before)
    print(f"[SIMULATED] has_drift={drift_before['has_drift']}, num_changes={drift_before['num_changes']}")
    print()

    print("[SIMULATED] --- Change made OUTSIDE Terraform: public access block disabled ---")
    print("[SIMULATED] --- AFTER: re-running the collector ---")
    client_after = get_s3_client(region_name="us-east-1")
    stubber_after = Stubber(client_after)
    _stub_drifted_responses(stubber_after, bucket_name)
    with stubber_after:
        raw_after = fetch_s3_bucket_raw_config(client_after, bucket_name)
    actual_after = normalize_s3_actual_state(raw_after, account_id="000000000000")

    return desired_state, actual_after, "simulated"


# ---------------------------------------------------------------------------
# Step 3: drift detection (existing, unmodified detect_drift)
# ---------------------------------------------------------------------------

def run_drift_detection(desired_state, actual_state, mode):
    tag = "REAL AWS" if mode == "real_aws" else "SIMULATED"
    print("=" * 78)
    print(f"STEP 3 [{tag}]: Drift detection (src/drift_engine.py -- unmodified)")
    print("=" * 78)
    drift_result = detect_drift(desired_state, actual_state)
    print(f"has_drift: {drift_result['has_drift']}")
    print(f"num_changes: {drift_result['num_changes']}")
    print(f"changed_attributes: {drift_result['changed_attributes']}")
    for change in drift_result["changes"]:
        print(f"  {change['attribute']}: {change['old_value']} -> {change['new_value']}")
    print()
    return drift_result


# ---------------------------------------------------------------------------
# Step 4: feature extraction + existing saved primary model (no retraining)
# ---------------------------------------------------------------------------

def run_feature_extraction_and_prediction(drift_result, mode):
    tag = "REAL AWS" if mode == "real_aws" else "SIMULATED"
    print("=" * 78)
    print(f"STEP 4 [{tag}]: Feature extraction + existing primary Random Forest model")
    print("=" * 78)
    features = extract_features("s3_bucket", drift_result, drift_frequency=0)
    print("Extracted features (feature_extraction.py -- unmodified):")
    print(json.dumps(features, indent=2))
    print()

    model = joblib.load(os.path.join(MODELS_DIR, "random_forest_model.joblib"))
    preprocessor = joblib.load(os.path.join(MODELS_DIR, "preprocessor.joblib"))
    with open(os.path.join(MODELS_DIR, "label_mapping.json")) as f:
        int_to_label = {int(k): v for k, v in json.load(f)["int_to_label"].items()}

    row = {col: features[col] for col in FEATURE_COLUMNS}
    df_row = pd.DataFrame([row])
    for col in BOOLEAN_FEATURES:
        df_row[col] = df_row[col].astype(int)

    X_transformed = preprocessor.transform(df_row)
    probabilities = model.predict_proba(X_transformed)[0]
    predicted_int = int(probabilities.argmax())
    predicted_label = int_to_label[predicted_int]

    print(f"PREDICTED RISK (primary Random Forest model, not retrained): {predicted_label}")
    print("Class probabilities:")
    for i, p in enumerate(probabilities):
        print(f"  {int_to_label[i]}: {p:.4f}")
    print()
    return features, predicted_label, probabilities


def main():
    parser = argparse.ArgumentParser(description="AWS S3 drift detection integration demo")
    parser.add_argument("--bucket", default=None, help="Real deployed bucket name (requires real AWS credentials)")
    args = parser.parse_args()

    creds_ok = run_real_credential_check()

    if creds_ok and args.bucket:
        try:
            desired_state, actual_state, mode = run_real_aws_path(args.bucket)
        except AWSConfigurationError as e:
            print(f"Real AWS path failed ({e.category}): {e.message}")
            print("Falling back to simulated demonstration.")
            desired_state, actual_state, mode = run_simulated_path(DEMO_BUCKET_NAME, str(e))
    else:
        ok, message, _ = check_aws_credentials()
        desired_state, actual_state, mode = run_simulated_path(args.bucket or DEMO_BUCKET_NAME, message)

    drift_result = run_drift_detection(desired_state, actual_state, mode)
    features, predicted_label, probabilities = run_feature_extraction_and_prediction(drift_result, mode)

    print("=" * 78)
    tag = "REAL AWS" if mode == "real_aws" else "SIMULATED"
    print(f"DEMONSTRATION COMPLETE -- MODE: [{tag}] (mode={mode})")
    if mode != "real_aws":
        print(
            "No real AWS call succeeded in this run. Every value above came from "
            "botocore Stubber-injected payloads, not a live AWS account. See "
            "README.md 'AWS Integration Milestone' section for the exact "
            "credential/network failure this environment produced, and the "
            "exact commands to run this same script against a real AWS account."
        )
    print("=" * 78)


if __name__ == "__main__":
    main()
