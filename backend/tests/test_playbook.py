"""Tests for the playbook loader service (validation, fast lookup, and filtering)."""

import json
import tempfile
from pathlib import Path
import pytest

from app.models.schemas import PlaybookRule
from app.services.playbook import get_rule, list_rules, load_playbook, rule_exists


def test_load_playbook_success() -> None:
    """Validate that the real playbook.json loads and caches all 13 rules."""
    rules = load_playbook(reload=True)
    assert len(rules) == 13
    assert all(isinstance(r, PlaybookRule) for r in rules)

    # Check distinct rule IDs
    rule_ids = [r.rule_id for r in rules]
    assert len(set(rule_ids)) == 13
    assert "LOL-01" in rule_ids
    assert "IND-01" in rule_ids
    assert "TRM-01" in rule_ids


def test_get_rule_valid_and_invalid() -> None:
    """Test get_rule with valid, case-insensitive, and invalid rule IDs."""
    load_playbook(reload=True)

    # Valid ID
    rule = get_rule("LOL-01")
    assert rule is not None
    assert rule.rule_id == "LOL-01"
    assert rule.clause_type == "limitation_of_liability"
    assert "Aggregate Liability Cap" in rule.title
    assert rule_exists("LOL-01") is True

    # Case-insensitive lookup
    rule_lower = get_rule("lol-01")
    assert rule_lower is not None
    assert rule_lower.rule_id == "LOL-01"

    # Invalid ID
    invalid_rule = get_rule("DOES_NOT_EXIST_999")
    assert invalid_rule is None
    assert rule_exists("DOES_NOT_EXIST_999") is False


def test_list_rules_filtered_and_unfiltered() -> None:
    """Test listing rules with and without clause_type filter."""
    load_playbook(reload=True)

    # Unfiltered: all 13 rules
    all_rules = list_rules(clause_type=None)
    assert len(all_rules) == 13

    # Filtered: limitation_of_liability has 2 rules (LOL-01, LOL-02)
    lol_rules = list_rules(clause_type="limitation_of_liability")
    assert len(lol_rules) == 2
    assert all(r.clause_type == "limitation_of_liability" for r in lol_rules)

    # Filtered: termination has 2 rules (TRM-01, TRM-02)
    trm_rules = list_rules(clause_type="termination")
    assert len(trm_rules) == 2

    # Non-existent clause type: empty list
    empty_rules = list_rules(clause_type="nonexistent_type")
    assert empty_rules == []


def test_load_playbook_duplicate_rule_id_fails() -> None:
    """Ensure duplicate rule_id in playbook causes validation failure."""
    duplicate_data = [
        {
            "rule_id": "TEST-01",
            "clause_type": "termination",
            "title": "First rule",
            "standard_position": "Standard",
            "acceptable_fallback": "Fallback",
            "unacceptable_triggers": [],
            "preferred_language": "Model",
            "rationale": "Reason",
        },
        {
            "rule_id": "TEST-01",  # Duplicate!
            "clause_type": "termination",
            "title": "Duplicate rule",
            "standard_position": "Standard",
            "acceptable_fallback": "Fallback",
            "unacceptable_triggers": [],
            "preferred_language": "Model",
            "rationale": "Reason",
        },
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(duplicate_data, tmp)
        tmp_path = Path(tmp.name)

    try:
        with pytest.raises(ValueError, match="Duplicate rule_id"):
            load_playbook(file_path=tmp_path, reload=True)
    finally:
        tmp_path.unlink(missing_ok=True)
        # Restore real playbook
        load_playbook(reload=True)


def test_load_playbook_invalid_structure_fails() -> None:
    """Ensure invalid JSON structure (not a list) raises ValueError."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump({"not": "a list"}, tmp)
        tmp_path = Path(tmp.name)

    try:
        with pytest.raises(ValueError, match="must be a list"):
            load_playbook(file_path=tmp_path, reload=True)
    finally:
        tmp_path.unlink(missing_ok=True)
        load_playbook(reload=True)


def test_load_playbook_missing_required_fields_fails() -> None:
    """Ensure rule missing mandatory fields fails Pydantic validation."""
    invalid_rule_data = [
        {
            "rule_id": "ERR-01",
            # Missing clause_type, standard_position, etc.
            "title": "Incomplete Rule",
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(invalid_rule_data, tmp)
        tmp_path = Path(tmp.name)

    try:
        with pytest.raises(ValueError, match="Validation error in playbook rule"):
            load_playbook(file_path=tmp_path, reload=True)
    finally:
        tmp_path.unlink(missing_ok=True)
        load_playbook(reload=True)
