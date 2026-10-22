"""Tests for src/frontend/remediation.py."""

import expansion_scenarios
import remediation
from feature_extraction import ATTRIBUTE_KNOWLEDGE_BASE


def test_every_known_attribute_has_a_fix():
    expansion_scenarios.install()
    missing = set(ATTRIBUTE_KNOWLEDGE_BASE) - set(remediation.FIXES)
    assert not missing, f"attributes without a recommended fix: {missing}"


def test_fix_fills_in_the_resource_id():
    fix = remediation.fix_for_attribute("block_public_access", {"bucket_name": "my-bucket"})
    assert "--bucket my-bucket" in fix["cli"]
    fix = remediation.fix_for_attribute("inbound_ssh.source_cidr", {"sg_id": "sg-123"})
    assert "--group-id sg-123" in fix["cli"]
    fix = remediation.fix_for_attribute("publicly_accessible", {"db_identifier": "orders-db-001"})
    assert "orders-db-001" in fix["cli"]


def test_unknown_id_keeps_a_placeholder_and_unknown_attribute_gives_none():
    assert "<bucket-name>" in remediation.fix_for_attribute("versioning", {})["cli"]
    assert remediation.fix_for_attribute("not_an_attribute") is None


def test_recommended_fixes_dedupes_attributes():
    changes = [{"attribute": "versioning"}, {"attribute": "versioning"}, {"attribute": "nope"}]
    assert len(remediation.recommended_fixes(changes)) == 1
