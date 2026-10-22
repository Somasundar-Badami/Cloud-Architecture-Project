"""
expansion_scenarios.py  --  DRAFT expansion pack (not part of the approved 20).

Adds 17 proposed scenarios on top of the approved 20:
    S8-S11   S3      (new attributes: KMS key, retention, TLS, MFA delete)
    E8-E11   EC2 SG  (HTTPS narrowed, public HTTP, public DB port, flow logs)
    I7-I9    IAM     (access keys, password policy, external id)
    R1-R6    RDS     (new resource type "rds_instance")

Nothing in the existing files is edited. `install()` registers the new
attribute rules into feature_extraction.ATTRIBUTE_KNOWLEDGE_BASE and appends
the new scenarios to the END of SCENARIO_REGISTRY, so the original 711 records
are generated first and stay byte-for-byte identical (same RNG stream).

Every risk_label below is a PROPOSAL. Each one must be approved by the team,
the same way the original 20 were. Labels were chosen so that
risk_rule_check.rule_based_label() agrees with them.
"""

import copy
from typing import Any, Dict

from scenario_definitions import (
    PUBLIC_CIDR, INTERNAL_CIDR_OPTIONS, SCENARIO_REGISTRY,
    s3_baseline, sg_baseline, iam_baseline, random_account_id,
)
import feature_extraction as fx

NONE_FLAGS = {
    "public_exposure": False,
    "encryption_change": False,
    "privilege_change": False,
    "port_exposure": "none",
}


def _flags(magnitude, **overrides):
    out = dict(NONE_FLAGS)
    out.update(overrides)
    out["change_magnitude"] = magnitude
    return out


# ---------------------------------------------------------------------------
# Extended baselines (only the NEW scenarios use these, so old records are
# untouched). No extra rng calls are made, only constant fields are added.
# ---------------------------------------------------------------------------

def s3_baseline_ext(rng, entity_id):
    d = s3_baseline(rng, entity_id)
    d["tls_enforced"] = True
    d["mfa_delete"] = "enabled"
    return d


def sg_baseline_ext(rng, entity_id):
    d = sg_baseline(rng, entity_id)
    d["inbound_http"] = None
    d["inbound_db"] = None
    d["flow_logs"] = "enabled"
    return d


def iam_baseline_ext(rng, entity_id):
    d = iam_baseline(rng, entity_id)
    d["access_key_count"] = 1
    d["password_min_length"] = 14
    d["external_id_required"] = True
    return d


def rds_baseline(rng, entity_id):
    return {
        "resource_type": "aws_db_instance",
        "db_identifier": f"orders-db-{entity_id:03d}",
        "publicly_accessible": False,
        "storage_encrypted": True,
        "backup_retention_days": rng.choice([7, 14, 30]),
        "deletion_protection": True,
        "multi_az": True,
        "iam_db_auth": True,
    }


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def mutate_S8(d, rng):
    a = copy.deepcopy(d); a["encryption"]["kms_key_id"] = "alias/aws/s3"; return a

def mutate_S9(d, rng):
    a = copy.deepcopy(d); a["lifecycle_rule"]["retention_days"] = 1; return a

def mutate_S10(d, rng):
    a = copy.deepcopy(d); a["tls_enforced"] = False; return a

def mutate_S11(d, rng):
    a = copy.deepcopy(d); a["mfa_delete"] = "disabled"; return a

def mutate_E8(d, rng):
    a = copy.deepcopy(d); a["inbound_https"]["source_cidr"] = rng.choice(INTERNAL_CIDR_OPTIONS); return a

def mutate_E9(d, rng):
    a = copy.deepcopy(d); a["inbound_http"] = {"port": 80, "source_cidr": PUBLIC_CIDR}; return a

def mutate_E10(d, rng):
    a = copy.deepcopy(d)
    a["inbound_db"] = {"port": rng.choice([3306, 5432, 1433]), "source_cidr": PUBLIC_CIDR}
    return a

def mutate_E11(d, rng):
    a = copy.deepcopy(d); a["flow_logs"] = "disabled"; return a

def mutate_I7(d, rng):
    a = copy.deepcopy(d); a["access_key_count"] = 2; return a

def mutate_I8(d, rng):
    a = copy.deepcopy(d); a["password_min_length"] = 6; return a

def mutate_I9(d, rng):
    a = copy.deepcopy(d); a["external_id_required"] = False; return a

def mutate_R1(d, rng):
    a = copy.deepcopy(d); a["publicly_accessible"] = True; return a

def mutate_R2(d, rng):
    a = copy.deepcopy(d); a["storage_encrypted"] = False; return a

def mutate_R3(d, rng):
    a = copy.deepcopy(d); a["backup_retention_days"] = 0; return a

def mutate_R4(d, rng):
    a = copy.deepcopy(d); a["deletion_protection"] = False; return a

def mutate_R5(d, rng):
    a = copy.deepcopy(d); a["multi_az"] = False; return a

def mutate_R6(d, rng):
    a = copy.deepcopy(d); a["iam_db_auth"] = False; return a


# ---------------------------------------------------------------------------
# Feature rules for the new attributes (same contract as feature_extraction)
# ---------------------------------------------------------------------------

def _rule_kms_key(old, new):
    swapped_to_default = isinstance(new, str) and new.startswith("alias/aws/")
    return _flags("Medium" if swapped_to_default else "Low")


def _rule_retention_days(old, new):
    shortened = isinstance(old, int) and isinstance(new, int) and new < old
    return _flags("Medium" if shortened else "Low")


def _rule_tls_enforced(old, new):
    weakened = old is True and new is False
    return _flags("Medium" if weakened else "Low", encryption_change=weakened)


def _rule_enabled_to_disabled(old, new):
    off = old in ("enabled", True) and new in ("disabled", False)
    return _flags("Medium" if off else "Low")


def _rule_https_source(old, new):
    return _flags("Low", port_exposure="internal")


def _rule_new_public_port(old, new):
    appeared = old is None and isinstance(new, dict)
    is_public = appeared and new.get("source_cidr") == PUBLIC_CIDR
    return _flags(
        "High" if is_public else ("Medium" if appeared else "Low"),
        public_exposure=is_public,
        port_exposure=PUBLIC_CIDR if is_public else ("internal" if appeared else "none"),
    )


def _rule_access_keys(old, new):
    return _flags("Low")


def _rule_password_length(old, new):
    weakened = isinstance(old, int) and isinstance(new, int) and new < old
    return _flags("Medium" if weakened else "Low")


def _rule_external_id(old, new):
    removed = old is True and new is False
    return _flags("Medium" if removed else "Low", privilege_change=removed)


def _rule_rds_public(old, new):
    became_public = old is False and new is True
    return _flags("High" if became_public else "Low", public_exposure=became_public,
                  port_exposure=PUBLIC_CIDR if became_public else "none")


def _rule_rds_encrypted(old, new):
    weakened = old is True and new is False
    return _flags("High" if weakened else "Low", encryption_change=weakened)


def _rule_rds_backup(old, new):
    reduced = isinstance(old, int) and isinstance(new, int) and new < old
    return _flags("High" if new == 0 else ("Medium" if reduced else "Low"))


def _rule_rds_toggle(old, new):
    return _flags("Medium" if (old is True and new is False) else "Low")


def _rule_rds_iam_auth(old, new):
    removed = old is True and new is False
    return _flags("Medium" if removed else "Low", privilege_change=removed)


# attribute path -> (resource_type, intrinsic sensitivity, rule)
NEW_KB_ENTRIES = {
    # S3
    "encryption.kms_key_id": ("s3_bucket", "Medium", _rule_kms_key),
    "lifecycle_rule.retention_days": ("s3_bucket", "Medium", _rule_retention_days),
    "tls_enforced": ("s3_bucket", "High", _rule_tls_enforced),
    "mfa_delete": ("s3_bucket", "Medium", _rule_enabled_to_disabled),
    # EC2 security group
    "inbound_https.source_cidr": ("security_group", "Low", _rule_https_source),
    "inbound_http": ("security_group", "Medium", _rule_new_public_port),
    "inbound_db": ("security_group", "High", _rule_new_public_port),
    "flow_logs": ("security_group", "Medium", _rule_enabled_to_disabled),
    # IAM
    "access_key_count": ("iam_policy", "Low", _rule_access_keys),
    "password_min_length": ("iam_policy", "Medium", _rule_password_length),
    "external_id_required": ("iam_policy", "High", _rule_external_id),
    # RDS
    "publicly_accessible": ("rds_instance", "High", _rule_rds_public),
    "storage_encrypted": ("rds_instance", "High", _rule_rds_encrypted),
    "backup_retention_days": ("rds_instance", "Medium", _rule_rds_backup),
    "deletion_protection": ("rds_instance", "Medium", _rule_rds_toggle),
    "multi_az": ("rds_instance", "Low", _rule_rds_toggle),
    "iam_db_auth": ("rds_instance", "High", _rule_rds_iam_auth),
}


def _sc(sid, rtype, label, n_ent, n_var, base, mut, desc):
    return {"scenario_id": sid, "resource_type": rtype, "risk_label": label,
            "n_entities": n_ent, "variations_per_entity": n_var,
            "baseline_fn": base, "mutate_fn": mut, "description": desc}


# Sizes: Critical 8x4=32, High 7x5=35, Medium 6x4=24, Low 8x5=40 per scenario.
NEW_SCENARIOS = [
    _sc("S8", "s3_bucket", "Medium", 6, 4, s3_baseline_ext, mutate_S8, "Customer KMS key swapped for the AWS default key"),
    _sc("S9", "s3_bucket", "Medium", 6, 4, s3_baseline_ext, mutate_S9, "Lifecycle retention shortened to 1 day"),
    _sc("S10", "s3_bucket", "High", 7, 5, s3_baseline_ext, mutate_S10, "HTTPS-only (TLS) enforcement removed"),
    _sc("S11", "s3_bucket", "Medium", 6, 4, s3_baseline_ext, mutate_S11, "MFA delete disabled"),
    _sc("E8", "security_group", "Low", 8, 5, sg_baseline_ext, mutate_E8, "HTTPS source narrowed from public to internal"),
    _sc("E9", "security_group", "High", 7, 5, sg_baseline_ext, mutate_E9, "Plain HTTP (80) opened to 0.0.0.0/0"),
    _sc("E10", "security_group", "Critical", 8, 4, sg_baseline_ext, mutate_E10, "Database port opened to 0.0.0.0/0"),
    _sc("E11", "security_group", "Medium", 6, 4, sg_baseline_ext, mutate_E11, "VPC flow logs disabled"),
    _sc("I7", "iam_policy", "Low", 8, 5, iam_baseline_ext, mutate_I7, "Extra access key created"),
    _sc("I8", "iam_policy", "Medium", 6, 4, iam_baseline_ext, mutate_I8, "Password policy minimum length lowered to 6"),
    _sc("I9", "iam_policy", "High", 7, 5, iam_baseline_ext, mutate_I9, "External ID requirement removed from role trust"),
    _sc("R1", "rds_instance", "Critical", 8, 4, rds_baseline, mutate_R1, "Database made publicly accessible"),
    _sc("R2", "rds_instance", "High", 7, 5, rds_baseline, mutate_R2, "Storage encryption disabled"),
    _sc("R3", "rds_instance", "Medium", 6, 4, rds_baseline, mutate_R3, "Automated backups turned off (retention 0)"),
    _sc("R4", "rds_instance", "Medium", 6, 4, rds_baseline, mutate_R4, "Deletion protection disabled"),
    _sc("R5", "rds_instance", "Low", 8, 5, rds_baseline, mutate_R5, "Multi-AZ disabled"),
    _sc("R6", "rds_instance", "High", 7, 5, rds_baseline, mutate_R6, "IAM database authentication disabled"),
]


def install():
    """Register the new rules and scenarios (idempotent)."""
    fx.ATTRIBUTE_KNOWLEDGE_BASE.update(NEW_KB_ENTRIES)
    have = {s["scenario_id"] for s in SCENARIO_REGISTRY}
    for s in NEW_SCENARIOS:
        if s["scenario_id"] not in have:
            SCENARIO_REGISTRY.append(s)
