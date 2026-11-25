"""Unit tests for dual-score evaluation calculations in eval_samples."""

from typing import Any, Dict

import pytest

from app.models.schemas import ClauseAnalysis, RiskLevel
from scripts.eval_samples import compute_dual_scores


def test_dual_score_computation_mocked_results() -> None:
    """Verify dual-score computation against both original and revised expected findings."""
    expected_findings: Dict[str, Dict[str, Any]] = {
        "contract_alpha.docx": {
            "1": {
                "clause_type": "confidentiality",
                "expected_risk": "Acceptable",
                "cited_rules": ["CNF-01"],
            },
            "2": {
                "clause_type": "indemnification",
                "original_expected_risk": "Needs Negotiation",
                "expected_risk": "Unacceptable",
                "cited_rules": ["IND-01"],
                "label_revision_note": "Hits unacceptable indemnity trigger.",
            },
        },
        "contract_beta.docx": {
            "1": {
                "clause_type": "data_protection",
                "original_expected_risk": "Acceptable",
                "expected_risk": "Needs Negotiation",
                "cited_rules": ["DAT-01"],
                "label_revision_note": "Fallback breach notification SLA.",
            },
            "2": {
                "clause_type": "termination",
                "expected_risk": "Acceptable",
                "cited_rules": ["TRM-01"],
            },
        },
    }

    mocked_actual_results: Dict[str, Dict[str, Any]] = {
        "contract_alpha.docx": {
            "1": {"risk_level": "Acceptable"},
            "2": {"risk_level": "Unacceptable"},
        },
        "contract_beta.docx": {
            # Use ClauseAnalysis model instance for contract_beta to test schema object handling
            "1": ClauseAnalysis(
                clause_id="C-001",
                clause_type="data_protection",
                risk_level=RiskLevel.NEEDS_NEGOTIATION,
                cited_rule_ids=["DAT-01"],
                explanation="Clause falls within acceptable fallback.",
                confidence=0.95,
            ),
            "2": ClauseAnalysis(
                clause_id="C-002",
                clause_type="termination",
                risk_level=RiskLevel.UNACCEPTABLE,  # Intentional diff
                cited_rule_ids=["TRM-01"],
                explanation="Termination triggers immediate cancellation.",
                confidence=0.9,
            ),
        },
    }

    summary = compute_dual_scores(mocked_actual_results, expected_findings)

    # Contract Alpha assertions:
    # Clause 1: actual Acceptable vs expected Acceptable -> matches both orig and revised
    # Clause 2: actual Unacceptable vs orig Needs Negotiation, rev Unacceptable -> matches revised, diffs orig
    alpha = summary["per_contract"]["contract_alpha.docx"]
    assert alpha["total_evaluated"] == 2
    assert alpha["original_matches"] == 1
    assert pytest.approx(alpha["original_pct"], 0.1) == 50.0
    assert alpha["revised_matches"] == 2
    assert pytest.approx(alpha["revised_pct"], 0.1) == 100.0

    # Contract Beta assertions:
    # Clause 1: actual Needs Negotiation vs orig Acceptable, rev Needs Negotiation -> matches revised, diffs orig
    # Clause 2: actual Unacceptable vs expected Acceptable -> diffs both
    beta = summary["per_contract"]["contract_beta.docx"]
    assert beta["total_evaluated"] == 2
    assert beta["original_matches"] == 0
    assert pytest.approx(beta["original_pct"], 0.1) == 0.0
    assert beta["revised_matches"] == 1
    assert pytest.approx(beta["revised_pct"], 0.1) == 50.0

    # Overall assertions:
    # 4 evaluated clauses total
    # Original matches: 1/4 = 25.0%
    # Revised matches: 3/4 = 75.0%
    overall = summary["overall"]
    assert overall["total_evaluated"] == 4
    assert overall["original_matches"] == 1
    assert pytest.approx(overall["original_pct"], 0.1) == 25.0
    assert overall["revised_matches"] == 3
    assert pytest.approx(overall["revised_pct"], 0.1) == 75.0

    # Revised clauses metadata assertions
    revised_clauses = summary["revised_clauses"]
    assert len(revised_clauses) == 2
    assert revised_clauses[0]["contract"] == "contract_alpha.docx"
    assert revised_clauses[0]["clause_key"] == "2"
    assert revised_clauses[0]["original_expected_risk"] == "Needs Negotiation"
    assert revised_clauses[0]["revised_expected_risk"] == "Unacceptable"
    assert revised_clauses[0]["actual_risk"] == "Unacceptable"
    assert revised_clauses[0]["label_revision_note"] == "Hits unacceptable indemnity trigger."

    assert revised_clauses[1]["contract"] == "contract_beta.docx"
    assert revised_clauses[1]["clause_key"] == "1"
    assert revised_clauses[1]["original_expected_risk"] == "Acceptable"
    assert revised_clauses[1]["revised_expected_risk"] == "Needs Negotiation"
    assert revised_clauses[1]["actual_risk"] == "Needs Negotiation"
    assert revised_clauses[1]["label_revision_note"] == "Fallback breach notification SLA."
