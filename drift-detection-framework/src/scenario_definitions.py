"""
scenario_definitions.py

Defines the 20 approved drift scenarios (frozen implementation spec,
Section 2) as reusable baseline generators + mutation functions, plus the
SCENARIO_REGISTRY that dataset_generator.py iterates over.

Scenario breakdown (matches the frozen spec exactly):
    S3 (7):   S1, S2, S3id, S4, S5, S6, S7
    EC2 (7):  E1, E2, E3, E4, E5 (non-drift control), E6, E7
    IAM (6):  I1, I2, I3, I4, I5, I6

risk_label on each registry entry is the APPROVED ground-truth label from
the frozen Section 3 rules (Low/Medium/High/Critical) -- it is NOT computed
here. See src/risk_rule_check.py for the independent rule-based consistency
check run during validation.

Every mutation function changes exactly the attribute(s) named in the
frozen scenario table, using the SAME field names that
src/feature_extraction.py's ATTRIBUTE_KNOWLEDGE_BASE expects (e.g.
"block_public_access", "encryption.enabled", "inbound_ssh.source_cidr").
This is what lets extract_features() run unmodified against generated
records without any KeyError.
"""

import copy
from typing import Any, Dict, Callable, Optional

PUBLIC_CIDR = "0.0.0.0/0"
INTERNAL_CIDR_OPTIONS = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]


# ---------------------------------------------------------------------------
# Small random-value helpers (all take an rng so generation stays
# reproducible under a single fixed seed passed in from dataset_generator.py)
# ---------------------------------------------------------------------------

def random_account_id(rng) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(12))


def random_sg_id(rng) -> str:
    return f"sg-{rng.randrange(0x100000, 0xFFFFFF):06x}"


# ---------------------------------------------------------------------------
# Baseline ("desired state") generators -- one per resource family.
# Each is reused by every scenario in that family so that only the field(s)
# named in the mutation function actually differ between desired and actual.
# ---------------------------------------------------------------------------

def s3_baseline(rng, entity_id: int) -> Dict[str, Any]:
    bucket_prefix = rng.choice(["prod", "staging", "dev", "app", "data", "backup"])
    account_id = random_account_id(rng)
    return {
        "resource_type": "aws_s3_bucket",
        "bucket_name": f"{bucket_prefix}-bucket-{entity_id:03d}",
        "block_public_access": True,
        "acl": "private",
        "encryption": {
            "enabled": True,
            "kms_key_id": f"alias/s3-key-{entity_id:03d}",
        },
        "versioning": "enabled",
        "logging": "enabled",
        "lifecycle_rule": {
            "enabled": True,
            "retention_days": rng.choice([90, 180, 365, 730]),
        },
        "bucket_policy_principal": f"arn:aws:iam::{account_id}:role/app-role-{entity_id:03d}",
    }


def sg_baseline(rng, entity_id: int) -> Dict[str, Any]:
    return {
        "resource_type": "aws_security_group",
        "sg_id": random_sg_id(rng),
        "instance_name": f"web-server-{entity_id:03d}",
        "inbound_ssh": {"port": 22, "source_cidr": rng.choice(INTERNAL_CIDR_OPTIONS)},
        "inbound_rdp": {"port": 3389, "source_cidr": rng.choice(INTERNAL_CIDR_OPTIONS)},
        "inbound_https": {"port": 443, "source_cidr": PUBLIC_CIDR},  # intended public web port
        "inbound_custom": None,
        "outbound_default": {"port": "all", "destination_cidr": rng.choice(INTERNAL_CIDR_OPTIONS)},
        "internal_service_port": {"port": rng.choice([5432, 3306, 6379]), "range": "single"},
        "peer_sg_reference": None,
    }


def iam_baseline(rng, entity_id: int) -> Dict[str, Any]:
    account_id = random_account_id(rng)
    return {
        "resource_type": "aws_iam_entity",
        "entity_name": f"app-role-{entity_id:03d}",
        "actions": [rng.choice(["s3:GetObject", "s3:ListBucket", "dynamodb:GetItem"])],
        "resources": [f"arn:aws:s3:::prod-data-{entity_id:03d}/*"],
        "effect": "Deny",
        "requires_mfa": True,
        "trust_principal": f"arn:aws:iam::{account_id}:root",
        "permissions_boundary": f"arn:aws:iam::{account_id}:policy/boundary-standard",
        "group_membership": "ReadOnlyGroup",
    }


# ---------------------------------------------------------------------------
# Mutation functions -- each returns the "actual state" by copying the
# desired state and changing exactly the field(s) the approved scenario
# describes.
# ---------------------------------------------------------------------------

def mutate_S1(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["block_public_access"] = False
    return actual


def mutate_S2(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["acl"] = "public-read"
    return actual


def mutate_S3id(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["encryption"]["enabled"] = False
    return actual


def mutate_S4(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["bucket_policy_principal"] = "*"
    return actual


def mutate_S5(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["versioning"] = "disabled"
    return actual


def mutate_S6(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["logging"] = "disabled"
    return actual


def mutate_S7(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["lifecycle_rule"] = None
    return actual


def mutate_E1(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["inbound_ssh"]["source_cidr"] = PUBLIC_CIDR
    return actual


def mutate_E2(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["inbound_rdp"]["source_cidr"] = PUBLIC_CIDR
    return actual


def mutate_E3(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    port = rng.randint(8000, 9000)
    actual["inbound_custom"] = {"port": port, "source_cidr": PUBLIC_CIDR}
    return actual


def mutate_E4(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["outbound_default"]["destination_cidr"] = PUBLIC_CIDR
    return actual


def mutate_E5_control(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    """Non-drift control case: actual state is an EXACT copy of desired."""
    return copy.deepcopy(desired)


def mutate_E6(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["internal_service_port"]["range"] = "5000-5999"
    return actual


def mutate_E7(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["peer_sg_reference"] = random_sg_id(rng)
    return actual


def mutate_I1(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["actions"] = ["*"]
    actual["resources"] = ["*"]
    return actual


def mutate_I2(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    new_account = random_account_id(rng)
    # guarantee the mutated account id actually differs (astronomically
    # unlikely to collide, but keep the guarantee explicit and cheap)
    while f"arn:aws:iam::{new_account}:root" == desired["trust_principal"]:
        new_account = random_account_id(rng)
    actual["trust_principal"] = f"arn:aws:iam::{new_account}:root"
    return actual


def mutate_I3(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["requires_mfa"] = False
    return actual


def mutate_I4(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["effect"] = "Allow"
    return actual


def mutate_I5(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["group_membership"] = "AdminGroup"
    return actual


def mutate_I6(desired: Dict[str, Any], rng) -> Dict[str, Any]:
    actual = copy.deepcopy(desired)
    actual["permissions_boundary"] = None
    return actual


# ---------------------------------------------------------------------------
# SCENARIO_REGISTRY
#
# n_entities x variations_per_entity is tuned per risk class so the final
# dataset lands close to an even ~175-180 records per class (see
# dataset_validation_report.json for the actual achieved counts):
#   Critical (9 templates): 5 entities x 4 variations = 20/template -> ~180
#   High     (5 templates): 7 entities x 5 variations = 35/template -> ~175
#   Medium   (4 templates): 11 entities x 4 variations = 44/template -> ~176
#   Low      (2 templates): 15 entities x 6 variations = 90/template -> ~180
# ---------------------------------------------------------------------------

SCENARIO_REGISTRY = [
    # --- S3 (7 scenarios) ---
    {"scenario_id": "S1", "resource_type": "s3_bucket", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S1,
     "description": "Public access block disabled"},
    {"scenario_id": "S2", "resource_type": "s3_bucket", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S2,
     "description": "Bucket ACL changed to public-read"},
    {"scenario_id": "S3id", "resource_type": "s3_bucket", "risk_label": "High",
     "n_entities": 7, "variations_per_entity": 5,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S3id,
     "description": "Server-side encryption disabled"},
    {"scenario_id": "S4", "resource_type": "s3_bucket", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S4,
     "description": "Bucket policy principal widened to wildcard"},
    {"scenario_id": "S5", "resource_type": "s3_bucket", "risk_label": "Medium",
     "n_entities": 11, "variations_per_entity": 4,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S5,
     "description": "Object versioning disabled"},
    {"scenario_id": "S6", "resource_type": "s3_bucket", "risk_label": "Medium",
     "n_entities": 11, "variations_per_entity": 4,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S6,
     "description": "Access logging disabled"},
    {"scenario_id": "S7", "resource_type": "s3_bucket", "risk_label": "Low",
     "n_entities": 15, "variations_per_entity": 6,
     "baseline_fn": s3_baseline, "mutate_fn": mutate_S7,
     "description": "Lifecycle/retention rule removed"},

    # --- EC2 Security Groups (7 scenarios, includes E5 non-drift control) ---
    {"scenario_id": "E1", "resource_type": "security_group", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E1,
     "description": "SSH (22) opened to 0.0.0.0/0"},
    {"scenario_id": "E2", "resource_type": "security_group", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E2,
     "description": "RDP (3389) opened to 0.0.0.0/0"},
    {"scenario_id": "E3", "resource_type": "security_group", "risk_label": "High",
     "n_entities": 7, "variations_per_entity": 5,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E3,
     "description": "Unplanned new port opened publicly"},
    {"scenario_id": "E4", "resource_type": "security_group", "risk_label": "High",
     "n_entities": 7, "variations_per_entity": 5,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E4,
     "description": "Outbound rule widened to allow-all"},
    {"scenario_id": "E5", "resource_type": "security_group", "risk_label": "Low",
     "n_entities": 15, "variations_per_entity": 6,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E5_control,
     "description": "Non-drift control case: no attribute changed"},
    {"scenario_id": "E6", "resource_type": "security_group", "risk_label": "Medium",
     "n_entities": 11, "variations_per_entity": 4,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E6,
     "description": "Internal service port widened to a range"},
    {"scenario_id": "E7", "resource_type": "security_group", "risk_label": "Medium",
     "n_entities": 11, "variations_per_entity": 4,
     "baseline_fn": sg_baseline, "mutate_fn": mutate_E7,
     "description": "Unplanned cross-security-group reference added"},

    # --- IAM (6 scenarios) ---
    {"scenario_id": "I1", "resource_type": "iam_policy", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": iam_baseline, "mutate_fn": mutate_I1,
     "description": "Policy escalated to full admin (Action:*, Resource:*)"},
    {"scenario_id": "I2", "resource_type": "iam_policy", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": iam_baseline, "mutate_fn": mutate_I2,
     "description": "Cross-account trust added to role"},
    {"scenario_id": "I3", "resource_type": "iam_policy", "risk_label": "High",
     "n_entities": 7, "variations_per_entity": 5,
     "baseline_fn": iam_baseline, "mutate_fn": mutate_I3,
     "description": "MFA condition removed"},
    {"scenario_id": "I4", "resource_type": "iam_policy", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": iam_baseline, "mutate_fn": mutate_I4,
     "description": "Explicit Deny flipped to Allow"},
    {"scenario_id": "I5", "resource_type": "iam_policy", "risk_label": "Critical",
     "n_entities": 5, "variations_per_entity": 4,
     "baseline_fn": iam_baseline, "mutate_fn": mutate_I5,
     "description": "User group membership escalated to AdminGroup"},
    {"scenario_id": "I6", "resource_type": "iam_policy", "risk_label": "High",
     "n_entities": 7, "variations_per_entity": 5,
     "baseline_fn": iam_baseline, "mutate_fn": mutate_I6,
     "description": "Permissions boundary removed"},
]

ALLOWED_RISK_LABELS = {"Low", "Medium", "High", "Critical"}

assert len(SCENARIO_REGISTRY) == 20, "Expected exactly 20 approved scenarios"
assert all(s["risk_label"] in ALLOWED_RISK_LABELS for s in SCENARIO_REGISTRY)
