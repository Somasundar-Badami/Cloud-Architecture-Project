"""
rds_collector.py  --  DRAFT. Fetches a live RDS instance with boto3 and
normalizes it into the schema expansion_scenarios.rds_baseline() produces
(publicly_accessible, storage_encrypted, backup_retention_days,
deletion_protection, multi_az, iam_db_auth). Mirrors sg_iam_collectors.py:
all AWS-response-shape knowledge lives here; drift_engine stays generic.
"""
from typing import Any, Dict


def fetch_rds_instance(rds_client, db_identifier: str) -> Dict[str, Any]:
    resp = rds_client.describe_db_instances(DBInstanceIdentifier=db_identifier)
    return resp["DBInstances"][0]


def normalize_rds_instance(db: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "resource_type": "aws_db_instance",
        "db_identifier": db["DBInstanceIdentifier"],
        "publicly_accessible": bool(db.get("PubliclyAccessible", False)),
        "storage_encrypted": bool(db.get("StorageEncrypted", False)),
        "backup_retention_days": int(db.get("BackupRetentionPeriod", 0)),
        "deletion_protection": bool(db.get("DeletionProtection", False)),
        "multi_az": bool(db.get("MultiAZ", False)),
        "iam_db_auth": bool(db.get("IAMDatabaseAuthenticationEnabled", False)),
    }
