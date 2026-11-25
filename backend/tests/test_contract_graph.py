"""Tests for the contract-level LangGraph analysis pipeline."""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.graph.contract_graph import analyze_contract, contract_analysis_graph
from app.models.schemas import (
    AnalysisOutput,
    ClassificationOutput,
    CombinedAnalysisOutput,
    ContractAnalysisResult,
    PlaybookRule,
    RedlineOutput,
    RiskLevel,
)


@pytest.fixture
def mock_retrieval_service():
    """Mock vector store retrieval to return deterministic rules based on clause type."""
    rules_map = {
        "limitation_of_liability": PlaybookRule(
            rule_id="LOL-01",
            clause_type="limitation_of_liability",
            title="Aggregate Liability Cap",
            standard_position="Cap at 12 months fees.",
            acceptable_fallback="Cap at 2x 12 months fees.",
            unacceptable_triggers=["unlimited liability"],
            preferred_language="12-month cap.",
            rationale="Limits exposure.",
        ),
        "termination": PlaybookRule(
            rule_id="TRM-01",
            clause_type="termination",
            title="Termination for Convenience",
            standard_position="30 days notice.",
            acceptable_fallback="60 days notice.",
            unacceptable_triggers=["no termination"],
            preferred_language="30-day termination.",
            rationale="Flexibility.",
        ),
    }

    async def fake_retrieve(clause_text, clause_type=None, top_k=3, **kwargs):
        if clause_type and clause_type in rules_map:
            return [(rules_map[clause_type], 0.95)]
        return [(rules_map["limitation_of_liability"], 0.80)]

    with patch("app.graph.clause_graph.retrieve_rules", side_effect=fake_retrieve):
        yield rules_map


@pytest.mark.anyio
async def test_contract_graph_full_pipeline_mocked(mock_retrieval_service) -> None:
    """Test full contract pipeline on sample_contract_compliant.docx with mocked LLM."""
    sample_path = Path("backend/data/samples/sample_contract_compliant.docx")
    assert sample_path.exists()

    async def mock_llm_dispatch(prompt, system_instruction, response_schema, **kwargs):
        if response_schema == CombinedAnalysisOutput:
            # Dynamically classify based on text content
            p_lower = prompt.lower()
            if "liability" in p_lower:
                ctype = "limitation_of_liability"
                rid = "LOL-01"
            elif "indemnif" in p_lower:
                ctype = "indemnification"
                rid = "IND-01"
            elif "terminat" in p_lower:
                ctype = "termination"
                rid = "TERM-01"
            elif "confidenti" in p_lower:
                ctype = "confidentiality"
                rid = "CONF-01"
            elif "governing law" in p_lower or "delaware" in p_lower:
                ctype = "governing_law"
                rid = "GOV-01"
            elif "intellectual property" in p_lower or "background ip" in p_lower:
                ctype = "ip_ownership"
                rid = "IP-01"
            elif "payment" in p_lower or "invoic" in p_lower:
                ctype = "payment_terms"
                rid = "PAY-01"
            elif "renew" in p_lower:
                ctype = "auto_renewal"
                rid = "REN-01"
            elif "data protection" in p_lower or "gdpr" in p_lower:
                ctype = "data_protection"
                rid = "DATA-01"
            elif "assign" in p_lower:
                ctype = "assignment"
                rid = "ASN-01"
            else:
                ctype = "limitation_of_liability"
                rid = "LOL-01"

            return {
                "clause_type": ctype,
                "risk_level": "Acceptable",
                "cited_rule_ids": [rid],
                "explanation": "Clause conforms to company playbook standard position.",
                "confidence": 0.95,
            }
        elif response_schema == ClassificationOutput:
            return {"clause_type": "limitation_of_liability", "confidence": 0.95}
        elif response_schema == AnalysisOutput:
            return {
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Clause conforms to company playbook standard position.",
                "confidence": 0.95,
            }
        elif response_schema == RedlineOutput:
            return {"suggested_redline": "Redline replacement text."}
        raise ValueError(f"Unexpected schema: {response_schema}")

    with patch("app.graph.clause_graph.generate_structured_json", side_effect=mock_llm_dispatch):
        result = await analyze_contract(sample_path)

        assert isinstance(result, ContractAnalysisResult)
        assert result.contract_name == "sample_contract_compliant.docx"
        assert result.total_clauses == 10
        assert len(result.analyses) == 10
        assert result.acceptable_count == 10
        assert result.needs_negotiation_count == 0
        assert result.unacceptable_count == 0
        assert result.needs_human_review_count == 0


@pytest.mark.anyio
async def test_contract_graph_single_clause_error_fault_tolerance(mock_retrieval_service) -> None:
    """Ensure a failure on one clause does not abort the entire contract run."""
    sample_path = Path("backend/data/samples/sample_contract_compliant.docx")

    call_count = 0

    async def mock_llm_dispatch(prompt, system_instruction, response_schema, **kwargs):
        nonlocal call_count
        call_count += 1

        if response_schema == CombinedAnalysisOutput:
            if "Section 3" in prompt or "Termination" in prompt:
                raise RuntimeError("Simulated transient LLM API crash on Section 3")
            return {
                "clause_type": "limitation_of_liability",
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Standard position met.",
                "confidence": 0.90,
            }
        elif response_schema == ClassificationOutput:
            if "Section 3" in prompt or "Termination" in prompt:
                raise RuntimeError("Simulated transient LLM API crash on Section 3")
            return {"clause_type": "limitation_of_liability", "confidence": 0.92}
        elif response_schema == AnalysisOutput:
            return {
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Standard position met.",
                "confidence": 0.90,
            }
        return {"suggested_redline": "Redline."}

    with (
        patch("app.graph.clause_graph.generate_structured_json", side_effect=mock_llm_dispatch),
        patch("app.core.config.settings.MAX_LLM_RETRIES", 0),  # fail immediately for test speed
    ):
        result = await analyze_contract(sample_path)

        # The run completes all 10 clauses despite the Section 3 failure!
        assert result.total_clauses == 10
        assert len(result.analyses) == 10

        # Section 3 should be flagged with needs_human_review
        failed_clause = next((a for a in result.analyses if "C-003" in a.clause_id), None)
        assert failed_clause is not None
        assert failed_clause.needs_human_review is True
        assert "Simulated transient LLM API crash" in (failed_clause.review_reason or "")

        # Other clauses succeeded
        successful_clauses = [a for a in result.analyses if a.clause_id != "C-003"]
        assert len(successful_clauses) == 9
        assert all(a.needs_human_review is False for a in successful_clauses)


@pytest.mark.anyio
async def test_contract_graph_missing_clause_check(mock_retrieval_service) -> None:
    """Ensure contract summarize node identifies unrepresented playbook clause types."""
    sample_path = Path("backend/data/samples/sample_contract_compliant.docx")

    # Force all clauses to classify ONLY as limitation_of_liability
    async def mock_llm_dispatch(prompt, system_instruction, response_schema, **kwargs):
        if response_schema == CombinedAnalysisOutput:
            return {
                "clause_type": "limitation_of_liability",
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Liability cap conforms to playbook.",
                "confidence": 0.90,
            }
        elif response_schema == ClassificationOutput:
            return {"clause_type": "limitation_of_liability", "confidence": 0.90}
        elif response_schema == AnalysisOutput:
            return {
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Liability cap conforms to playbook.",
                "confidence": 0.90,
            }
        return {"suggested_redline": "Redline."}

    with patch("app.graph.clause_graph.generate_structured_json", side_effect=mock_llm_dispatch):
        result = await analyze_contract(sample_path)

        # All other 9 clause types should be in missing_clause_types
        assert "limitation_of_liability" not in result.missing_clause_types
        assert "indemnification" in result.missing_clause_types
        assert "termination" in result.missing_clause_types
        assert "confidentiality" in result.missing_clause_types
        assert len(result.missing_clause_types) == 9
