"""
tests/test_compliance.py

Tests for src/frontend/compliance.py: every attribute the model knows
must have a compliance mapping, and the helper functions must handle
known, unknown and duplicate attributes.
"""

import compliance
from feature_extraction import ATTRIBUTE_KNOWLEDGE_BASE


def test_every_known_attribute_has_a_mapping():
    missing = set(ATTRIBUTE_KNOWLEDGE_BASE) - set(compliance.CONTROL_MAP)
    assert not missing, f"attributes without a compliance mapping: {missing}"


def test_mapping_has_no_attributes_outside_the_model_schema():
    extra = set(compliance.CONTROL_MAP) - set(ATTRIBUTE_KNOWLEDGE_BASE)
    assert not extra


def test_every_mapping_is_well_formed():
    for attribute, m in compliance.CONTROL_MAP.items():
        assert m["match"] in ("direct", "related"), attribute
        assert isinstance(m["security_hub"], list), attribute
        assert m["title"], attribute
        assert m["cis"] is None or all(p.isdigit() for p in m["cis"].split(".")), attribute


def test_public_ssh_maps_to_cis_5_2():
    m = compliance.controls_for_attribute("inbound_ssh.source_cidr")
    assert m["cis"] == "5.2"
    assert m["match"] == "direct"
    assert "EC2.13" in m["security_hub"]


def test_unknown_attribute_returns_none():
    assert compliance.controls_for_attribute("tags.Owner") is None


def test_compliance_rows_one_row_per_change_including_unknown():
    changes = [
        {"attribute": "block_public_access", "old_value": True, "new_value": False},
        {"attribute": "tags.Owner", "old_value": "a", "new_value": "b"},
    ]
    rows = compliance.compliance_rows(changes)
    assert len(rows) == 2
    assert rows[0]["cis_control"] == "CIS 2.1.5"
    assert rows[1]["match"] == "unmapped"


def test_compliance_rows_attribute_without_cis_shows_dash():
    rows = compliance.compliance_rows([{"attribute": "lifecycle_rule", "old_value": 1, "new_value": None}])
    assert rows[0]["cis_control"] == "—"
    assert rows[0]["security_hub"] == "S3.13"


def test_violated_cis_controls_sorted_numerically_and_deduplicated():
    changes = [{"attribute": a} for a in ("actions", "resources", "inbound_ssh.source_cidr", "access_key_count")]
    assert compliance.violated_cis_controls(changes) == ["1.13", "1.16", "5.2"]


def test_violated_cis_controls_empty_for_no_changes():
    assert compliance.violated_cis_controls([]) == []
