"""Tests for Pydantic models and schemas."""

import json
from pathlib import Path
import pytest
from app.models.schemas import (
    Clause,
    ClauseAnalysis,
    DecisionStatus,
    PlaybookRule,
    ReviewDecision,
    ReviewReport,
    RiskLevel,
)


def test_playbook_json_loading() -> None:
    """Validate that all entries in playbook.json parse into PlaybookRule models."""
    playbook_path = Path("backend/data/playbook.json")
    assert playbook_path.exists(), "playbook.json must exist"

    with open(playbook_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    assert len(data) >= 10

    rules = [PlaybookRule(**item) for item in data]
    rule_ids = {r.rule_id for r in rules}
    assert len(rule_ids) == len(rules), "All rule IDs must be unique"

    clause_types = {r.clause_type for r in rules}
    required_clause_types = {
        "limitation_of_liability",
        "indemnification",
        "termination",
        "confidentiality",
        "governing_law",
        "ip_ownership",
        "payment_terms",
        "auto_renewal",
        "data_protection",
        "assignment",
    }
    assert required_clause_types.issubset(clause_types)


def test_clause_analysis_model() -> None:
    """Ensure ClauseAnalysis model validates valid and invalid ranges."""
    analysis = ClauseAnalysis(
        clause_id="clause-1",
        clause_type="limitation_of_liability",
        risk_level=RiskLevel.UNACCEPTABLE,
        cited_rule_ids=["LOL-01"],
        explanation="Unlimited liability triggers rule LOL-01.",
        suggested_redline="Cap liability at 12 months fees.",
        confidence=0.95,
    )
    assert analysis.risk_level == RiskLevel.UNACCEPTABLE
    assert analysis.confidence == 0.95

    # Out-of-bounds confidence score should raise ValidationError
    with pytest.raises(Exception):
        ClauseAnalysis(
            clause_id="clause-1",
            clause_type="limitation_of_liability",
            risk_level=RiskLevel.UNACCEPTABLE,
            cited_rule_ids=["LOL-01"],
            explanation="Invalid confidence.",
            confidence=1.5,
        )


def test_review_report_model() -> None:
    """Ensure ReviewReport validates properly."""
    report = ReviewReport(
        report_id="rep-001",
        contract_name="sample_contract_compliant.docx",
        total_clauses=1,
        acceptable_count=1,
        needs_negotiation_count=0,
        unacceptable_count=0,
        analyses=[
            ClauseAnalysis(
                clause_id="clause-1",
                clause_type="limitation_of_liability",
                risk_level=RiskLevel.ACCEPTABLE,
                cited_rule_ids=["LOL-01"],
                explanation="12-month cap conforms to standard position.",
                confidence=0.99,
            )
        ],
    )
    assert report.total_clauses == 1
    assert "ADVISORY ONLY" in report.disclaimer
