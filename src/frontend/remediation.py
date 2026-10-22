"""
remediation.py

Turns a detected drift into a recommended fix: a one-line action and an
AWS CLI command (with the resource id filled in when it is known).
The fix is advice only: the dashboard never runs anything.

The primary fix is always "re-apply Terraform", because Terraform is the
source of truth; the CLI command is the quick manual equivalent.

No Streamlit calls in here, so it is unit-testable.
"""

from typing import Any, Dict, Iterable, List

# attribute -> (what to do, AWS CLI command). {bucket} {sg} {role} {db} are filled from the
# desired state; anything unknown stays as a <placeholder> for the operator to fill in.
FIXES: Dict[str, Dict[str, str]] = {
    # --- S3 ---
    "block_public_access": {
        "action": "Turn S3 Block Public Access back on for the bucket.",
        "cli": "aws s3api put-public-access-block --bucket {bucket} --public-access-block-configuration "
               "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"},
    "acl": {
        "action": "Reset the bucket ACL to private.",
        "cli": "aws s3api put-bucket-acl --bucket {bucket} --acl private"},
    "encryption.enabled": {
        "action": "Re-enable default server-side encryption (KMS).",
        "cli": "aws s3api put-bucket-encryption --bucket {bucket} --server-side-encryption-configuration "
               "'{{\"Rules\":[{{\"ApplyServerSideEncryptionByDefault\":{{\"SSEAlgorithm\":\"aws:kms\"}}}}]}}'"},
    "encryption.kms_key_id": {
        "action": "Point default encryption back at the customer-managed KMS key.",
        "cli": "aws s3api put-bucket-encryption --bucket {bucket} --server-side-encryption-configuration "
               "'{{\"Rules\":[{{\"ApplyServerSideEncryptionByDefault\":{{\"SSEAlgorithm\":\"aws:kms\","
               "\"KMSMasterKeyID\":\"<kms-key-arn>\"}}}}]}}'"},
    "bucket_policy_principal": {
        "action": "Restore the approved bucket policy so only the intended principals have access.",
        "cli": "aws s3api put-bucket-policy --bucket {bucket} --policy file://approved-policy.json"},
    "versioning": {
        "action": "Turn bucket versioning back on.",
        "cli": "aws s3api put-bucket-versioning --bucket {bucket} --versioning-configuration Status=Enabled"},
    "logging": {
        "action": "Re-enable server access logging.",
        "cli": "aws s3api put-bucket-logging --bucket {bucket} --bucket-logging-status file://logging.json"},
    "lifecycle_rule": {
        "action": "Restore the approved lifecycle rule.",
        "cli": "aws s3api put-bucket-lifecycle-configuration --bucket {bucket} --lifecycle-configuration file://lifecycle.json"},
    "lifecycle_rule.retention_days": {
        "action": "Restore the approved retention period in the lifecycle rule.",
        "cli": "aws s3api put-bucket-lifecycle-configuration --bucket {bucket} --lifecycle-configuration file://lifecycle.json"},
    "tls_enforced": {
        "action": "Add back the bucket policy statement that denies requests without HTTPS (aws:SecureTransport = false).",
        "cli": "aws s3api put-bucket-policy --bucket {bucket} --policy file://approved-policy.json"},
    "mfa_delete": {
        "action": "Re-enable MFA delete (only the root user can do this).",
        "cli": "aws s3api put-bucket-versioning --bucket {bucket} --versioning-configuration "
               "Status=Enabled,MFADelete=Enabled --mfa \"<mfa-device-arn> <code>\""},
    # --- EC2 security group ---
    "inbound_ssh.source_cidr": {
        "action": "Remove the public SSH rule (port 22) and allow only the internal range.",
        "cli": "aws ec2 revoke-security-group-ingress --group-id {sg} --protocol tcp --port 22 --cidr 0.0.0.0/0"},
    "inbound_rdp.source_cidr": {
        "action": "Remove the public RDP rule (port 3389) and allow only the internal range.",
        "cli": "aws ec2 revoke-security-group-ingress --group-id {sg} --protocol tcp --port 3389 --cidr 0.0.0.0/0"},
    "inbound_custom": {
        "action": "Remove the unapproved inbound rule.",
        "cli": "aws ec2 revoke-security-group-ingress --group-id {sg} --protocol tcp --port <port> --cidr <cidr>"},
    "outbound_default.destination_cidr": {
        "action": "Put the outbound rule back to the approved destination.",
        "cli": "aws ec2 revoke-security-group-egress --group-id {sg} --protocol -1 --cidr 0.0.0.0/0"},
    "internal_service_port.range": {
        "action": "Restore the approved port range for the internal service.",
        "cli": "aws ec2 revoke-security-group-ingress --group-id {sg} --protocol tcp --port <port-range> --cidr <cidr>"},
    "peer_sg_reference": {
        "action": "Restore the approved peer security group reference (re-apply Terraform).",
        "cli": "aws ec2 describe-security-groups --group-ids {sg}"},
    "inbound_https.source_cidr": {
        "action": "HTTPS source was narrowed; confirm this is intended, otherwise re-apply Terraform.",
        "cli": "aws ec2 describe-security-groups --group-ids {sg}"},
    "inbound_http": {
        "action": "Remove the public HTTP rule (port 80); serve HTTPS only.",
        "cli": "aws ec2 revoke-security-group-ingress --group-id {sg} --protocol tcp --port 80 --cidr 0.0.0.0/0"},
    "inbound_db": {
        "action": "Close the database port to the internet; allow only the application security group.",
        "cli": "aws ec2 revoke-security-group-ingress --group-id {sg} --protocol tcp --port <db-port> --cidr 0.0.0.0/0"},
    "flow_logs": {
        "action": "Turn VPC flow logs back on.",
        "cli": "aws ec2 create-flow-logs --resource-type VPC --resource-ids <vpc-id> --traffic-type ALL "
               "--log-destination-type cloud-watch-logs --log-group-name <log-group> "
               "--deliver-logs-permission-arn <role-arn>"},
    # --- IAM ---
    "actions": {
        "action": "Restore the approved action list in the role's policy.",
        "cli": "aws iam put-role-policy --role-name {role} --policy-name <policy-name> --policy-document file://approved-policy.json"},
    "resources": {
        "action": "Restore the approved resource list in the role's policy.",
        "cli": "aws iam put-role-policy --role-name {role} --policy-name <policy-name> --policy-document file://approved-policy.json"},
    "effect": {
        "action": "Restore the approved Allow/Deny effect in the role's policy.",
        "cli": "aws iam put-role-policy --role-name {role} --policy-name <policy-name> --policy-document file://approved-policy.json"},
    "trust_principal": {
        "action": "Restore the approved trust policy so only the intended principal can assume the role.",
        "cli": "aws iam update-assume-role-policy --role-name {role} --policy-document file://approved-trust.json"},
    "requires_mfa": {
        "action": "Require MFA again (aws:MultiFactorAuthPresent condition) in the policy.",
        "cli": "aws iam put-role-policy --role-name {role} --policy-name <policy-name> --policy-document file://approved-policy.json"},
    "group_membership": {
        "action": "Remove the entity from the group it should not be in.",
        "cli": "aws iam remove-user-from-group --user-name {role} --group-name <group-name>"},
    "permissions_boundary": {
        "action": "Re-attach the approved permissions boundary.",
        "cli": "aws iam put-role-permissions-boundary --role-name {role} --permissions-boundary <boundary-policy-arn>"},
    "access_key_count": {
        "action": "Delete the extra access key (keep one).",
        "cli": "aws iam delete-access-key --user-name {role} --access-key-id <extra-key-id>"},
    "password_min_length": {
        "action": "Raise the account password minimum length back to 14.",
        "cli": "aws iam update-account-password-policy --minimum-password-length 14"},
    "external_id_required": {
        "action": "Require the external id again in the role's trust policy (sts:ExternalId condition).",
        "cli": "aws iam update-assume-role-policy --role-name {role} --policy-document file://approved-trust.json"},
    # --- RDS ---
    "publicly_accessible": {
        "action": "Make the database private again.",
        "cli": "aws rds modify-db-instance --db-instance-identifier {db} --no-publicly-accessible --apply-immediately"},
    "storage_encrypted": {
        "action": "Encryption cannot be switched on in place: snapshot, copy the snapshot with a KMS key, "
                  "and restore it as a new encrypted instance.",
        "cli": "aws rds copy-db-snapshot --source-db-snapshot-identifier <snapshot> "
               "--target-db-snapshot-identifier <snapshot>-enc --kms-key-id <kms-key-arn>"},
    "backup_retention_days": {
        "action": "Turn automated backups back on with the approved retention.",
        "cli": "aws rds modify-db-instance --db-instance-identifier {db} --backup-retention-period 7 --apply-immediately"},
    "deletion_protection": {
        "action": "Turn deletion protection back on.",
        "cli": "aws rds modify-db-instance --db-instance-identifier {db} --deletion-protection --apply-immediately"},
    "multi_az": {
        "action": "Turn Multi-AZ back on.",
        "cli": "aws rds modify-db-instance --db-instance-identifier {db} --multi-az --apply-immediately"},
    "iam_db_auth": {
        "action": "Turn IAM database authentication back on.",
        "cli": "aws rds modify-db-instance --db-instance-identifier {db} --enable-iam-database-authentication --apply-immediately"},
}

TERRAFORM_STEP = "Preferred: run `terraform apply` so the live resource matches the Terraform code again."


def _ids(desired_state: Dict[str, Any]) -> Dict[str, str]:
    d = desired_state if isinstance(desired_state, dict) else {}
    return {
        "bucket": str(d.get("bucket_name", "<bucket-name>")),
        "sg": str(d.get("sg_id", "<security-group-id>")),
        "role": str(d.get("entity_name", "<role-or-user-name>")),
        "db": str(d.get("db_identifier", "<db-identifier>")),
    }


def fix_for_attribute(attribute: str, desired_state: Dict[str, Any] = None):
    """Returns {"attribute", "action", "cli"} or None when there is no recommendation."""
    fix = FIXES.get(attribute)
    if fix is None:
        return None
    return {"attribute": attribute, "action": fix["action"], "cli": fix["cli"].format(**_ids(desired_state))}


def recommended_fixes(changes: Iterable[Dict[str, Any]], desired_state: Dict[str, Any] = None) -> List[Dict[str, str]]:
    """One entry per distinct changed attribute that has a known fix."""
    out, seen = [], set()
    for ch in changes:
        attr = ch.get("attribute")
        if attr in seen:
            continue
        seen.add(attr)
        fix = fix_for_attribute(attr, desired_state)
        if fix:
            out.append(fix)
    return out
