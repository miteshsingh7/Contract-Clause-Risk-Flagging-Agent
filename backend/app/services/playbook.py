"""Playbook loader service.

Loads, validates, and caches the corporate negotiation playbook from JSON.
Provides fast in-memory rule lookups (get_rule) and filtered listings (list_rules).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union

from app.models.schemas import PlaybookRule

logger = logging.getLogger(__name__)

# Default relative location of the playbook JSON file
DEFAULT_PLAYBOOK_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "playbook.json"

# In-memory storage for loaded playbook rules
_PLAYBOOK_RULES: Dict[str, PlaybookRule] = {}
_PLAYBOOK_ORDERED_LIST: List[PlaybookRule] = []


def get_default_playbook_path() -> Path:
    """Return the default path to data/playbook.json."""
    return DEFAULT_PLAYBOOK_PATH


def load_playbook(
    file_path: Optional[Union[str, Path]] = None,
    reload: bool = False,
) -> List[PlaybookRule]:
    """Load and validate the playbook JSON file.

    Args:
        file_path: Optional path to the playbook JSON file. Defaults to data/playbook.json.
        reload: If True, forces re-reading from disk even if already cached.

    Returns:
        List of validated PlaybookRule instances.

    Raises:
        FileNotFoundError: If the playbook file does not exist.
        ValueError: If JSON structure is invalid, duplicate rule_ids exist, or validation fails.
    """
    global _PLAYBOOK_RULES, _PLAYBOOK_ORDERED_LIST

    if _PLAYBOOK_RULES and not reload:
        return _PLAYBOOK_ORDERED_LIST

    path = Path(file_path) if file_path else DEFAULT_PLAYBOOK_PATH

    if not path.exists():
        raise FileNotFoundError(f"Playbook file not found at: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except json.JSONDecodeError as err:
        raise ValueError(f"Playbook file contains invalid JSON: {err}") from err

    if not isinstance(raw_data, list):
        raise ValueError("Playbook JSON must be a list of rule objects.")

    rules_by_id: Dict[str, PlaybookRule] = {}
    ordered_rules: List[PlaybookRule] = []

    for index, item in enumerate(raw_data):
        if not isinstance(item, dict):
            raise ValueError(f"Rule entry at index {index} is not a valid JSON object.")

        try:
            rule = PlaybookRule.model_validate(item)
        except Exception as val_err:
            raise ValueError(
                f"Validation error in playbook rule at index {index}: {val_err}"
            ) from val_err

        normalized_id = rule.rule_id.strip()
        if not normalized_id:
            raise ValueError(f"Rule at index {index} has an empty rule_id.")

        if normalized_id in rules_by_id:
            raise ValueError(
                f"Duplicate rule_id found in playbook: '{normalized_id}' at index {index}."
            )

        rules_by_id[normalized_id] = rule
        ordered_rules.append(rule)

    _PLAYBOOK_RULES = rules_by_id
    _PLAYBOOK_ORDERED_LIST = ordered_rules

    logger.info("Successfully loaded and validated %d playbook rules.", len(ordered_rules))
    return _PLAYBOOK_ORDERED_LIST


def get_rule(rule_id: str) -> Optional[PlaybookRule]:
    """Retrieve a playbook rule by its unique rule_id.

    Args:
        rule_id: The rule identifier (e.g. 'LOL-01').

    Returns:
        The matching PlaybookRule or None if not found.
    """
    if not _PLAYBOOK_RULES:
        load_playbook()

    target = rule_id.strip()
    # Match exact or case-insensitive
    if target in _PLAYBOOK_RULES:
        return _PLAYBOOK_RULES[target]

    for rid, rule in _PLAYBOOK_RULES.items():
        if rid.lower() == target.lower():
            return rule

    return None


def list_rules(clause_type: Optional[str] = None) -> List[PlaybookRule]:
    """List playbook rules, optionally filtered by clause type.

    Args:
        clause_type: Optional clause type to filter by (e.g. 'limitation_of_liability').

    Returns:
        List of matching PlaybookRule objects.
    """
    if not _PLAYBOOK_RULES:
        load_playbook()

    if clause_type is None:
        return list(_PLAYBOOK_ORDERED_LIST)

    target_type = clause_type.strip().lower()
    return [
        rule for rule in _PLAYBOOK_ORDERED_LIST
        if rule.clause_type.strip().lower() == target_type
    ]


def rule_exists(rule_id: str) -> bool:
    """Return True if a rule with the specified rule_id exists in the playbook."""
    return get_rule(rule_id) is not None
