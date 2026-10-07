"""
cloud_client.py

Thin client the Streamlit dashboard uses to talk to the deployed AWS
stack: Cognito sign-in (USER_PASSWORD_AUTH, incl. the first-login
NEW_PASSWORD_REQUIRED challenge) and the API Gateway endpoints.

No Streamlit calls in here, so it is unit-testable.

Configuration is read, in order, from:
  1. environment variables  IDG_API_URL, IDG_COGNITO_CLIENT_ID, IDG_REGION
  2. src/aws/terraform/outputs.json  (written by: terraform output -json > outputs.json)
"""

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

import boto3
from botocore import UNSIGNED
from botocore.config import Config

import project_paths

OUTPUTS_FILE = os.path.join(project_paths.TERRAFORM_DIR, "outputs.json")


class CloudError(Exception):
    pass


def load_config() -> Dict[str, Optional[str]]:
    cfg = {"api_url": None, "client_id": None, "region": None}
    if os.path.exists(OUTPUTS_FILE):
        with open(OUTPUTS_FILE) as f:
            outputs = json.load(f)
        cfg["api_url"] = outputs.get("api_url", {}).get("value")
        cfg["client_id"] = outputs.get("cognito_client_id", {}).get("value")
        cfg["region"] = outputs.get("aws_region", {}).get("value")
    cfg["api_url"] = os.environ.get("IDG_API_URL", cfg["api_url"])
    cfg["client_id"] = os.environ.get("IDG_COGNITO_CLIENT_ID", cfg["client_id"])
    cfg["region"] = os.environ.get("IDG_REGION", cfg["region"] or "us-east-1")
    return cfg


def _cognito(region: str):
    # InitiateAuth / RespondToAuthChallenge are public APIs -- no AWS
    # credentials needed on the dashboard machine.
    return boto3.client("cognito-idp", region_name=region, config=Config(signature_version=UNSIGNED))


def sign_in(region: str, client_id: str, username: str, password: str,
            new_password: Optional[str] = None) -> Dict[str, Any]:
    """Returns {"id_token": ...} or {"challenge": "NEW_PASSWORD_REQUIRED"}."""
    client = _cognito(region)
    try:
        resp = client.initiate_auth(
            ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        if resp.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
            if not new_password:
                return {"challenge": "NEW_PASSWORD_REQUIRED"}
            resp = client.respond_to_auth_challenge(
                ClientId=client_id, ChallengeName="NEW_PASSWORD_REQUIRED", Session=resp["Session"],
                ChallengeResponses={"USERNAME": username, "NEW_PASSWORD": new_password},
            )
    except client.exceptions.NotAuthorizedException:
        raise CloudError("Incorrect username or password.")
    except client.exceptions.InvalidPasswordException as e:
        raise CloudError(f"New password rejected: {e}")
    except Exception as e:  # network, misconfiguration
        raise CloudError(f"Sign-in failed: {e}")
    return {"id_token": resp["AuthenticationResult"]["IdToken"]}


def call_api(api_url: str, id_token: str, method: str, path: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        api_url.rstrip("/") + path, method=method,
        headers={"Authorization": id_token, "Content-Type": "application/json"},
        data=b"{}" if method == "POST" else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise CloudError("Session expired -- please sign in again.")
        raise CloudError(f"API error {e.code}: {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        raise CloudError(f"Could not reach the API: {e.reason}")
