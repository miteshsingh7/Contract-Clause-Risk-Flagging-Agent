"""Tests for contract clause segmentation and LLM boundary refinement."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from docx import Document
from fpdf import FPDF

from app.models.schemas import (
    Clause,
    MergeCorrection,
    ParsedDocument,
    ParsedParagraph,
    RefinementPlan,
    SplitCorrection,
)
from app.services.parser import parse_document
from app.services.segmenter import segment_document
from app.services.segment_refine import refine_clauses_with_llm


@pytest.mark.anyio
async def test_segment_sample_contract_compliant() -> None:
    """Test segmentation on sample_contract_compliant.docx."""
    sample_path = Path("backend/data/samples/sample_contract_compliant.docx")
    parsed = parse_document(sample_path)
    result = await segment_document(parsed, enable_llm_refinement=False)

    # Assert exactly 10 top-level substantive clauses
    assert result.total_substantive_clauses == 10
    assert len(result.clauses) == 10

    # Assert preamble is captured as non-substantive
    assert result.preamble is not None
    assert "MASTER SERVICES AGREEMENT" in result.preamble
    assert "This Master Services Agreement" in result.preamble

    # Assert expected sequential IDs and section numbers
    for idx, clause in enumerate(result.clauses, 1):
        assert clause.id == f"C-{idx:03d}"
        assert clause.section_number == str(idx)
        assert clause.title is not None
        assert len(clause.title) > 0
        assert clause.clause_type is None  # Step 4 will populate clause_type

    # Assert sub-clauses stay inside parent clauses
    c1 = result.clauses[0]
    assert c1.section_number == "1"
    assert "Limitation of Liability" in c1.title
    assert "1.1 Aggregate Liability Cap." in c1.text
    assert "1.2 Waiver of Consequential Damages." in c1.text

    c2 = result.clauses[1]
    assert c2.section_number == "2"
    assert "Indemnification" in c2.title
    assert "2.1 Intellectual Property Indemnification." in c2.text
    assert "2.2 Mutual General Indemnity." in c2.text

    c3 = result.clauses[2]
    assert c3.section_number == "3"
    assert "Term and Termination" in c3.title
    assert "3.1 Termination for Convenience." in c3.text
    assert "3.2 Termination for Material Breach and Insolvency." in c3.text


@pytest.mark.anyio
async def test_segment_sample_contract_needs_negotiation() -> None:
    """Test segmentation on sample_contract_needs_negotiation.docx."""
    sample_path = Path("backend/data/samples/sample_contract_needs_negotiation.docx")
    parsed = parse_document(sample_path)
    result = await segment_document(parsed, enable_llm_refinement=False)

    assert result.total_substantive_clauses == 10
    assert len(result.clauses) == 10

    # Verify Section 1 includes both 1.1 and 1.2
    c1 = result.clauses[0]
    assert c1.section_number == "1"
    assert "1.1 Aggregate Liability Cap." in c1.text
    assert "1.2 Consequential Damages and Super-Cap." in c1.text


@pytest.mark.anyio
async def test_segment_sample_contract_unacceptable() -> None:
    """Test segmentation on sample_contract_unacceptable.docx."""
    sample_path = Path("backend/data/samples/sample_contract_unacceptable.docx")
    parsed = parse_document(sample_path)
    result = await segment_document(parsed, enable_llm_refinement=False)

    assert result.total_substantive_clauses == 10
    assert len(result.clauses) == 10

    c1 = result.clauses[0]
    assert c1.section_number == "1"
    assert "1.1 Uncapped Liability of Company and Unilateral Cap." in c1.text
    assert "1.2 One-Sided Consequential Damages and Lost Profits." in c1.text


@pytest.mark.anyio
async def test_segment_unnumbered_contract() -> None:
    """Test fallback segmentation on contracts with no numbering (using Heading styles)."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        doc_path = Path(tmp.name)

    doc = Document()
    doc.add_heading("NON-DISCLOSURE AGREEMENT", level=0)
    doc.add_paragraph("This Agreement is entered into by the parties.")

    doc.add_heading("Confidentiality Obligations", level=1)
    doc.add_paragraph("The receiving party agrees to hold all proprietary materials confidential.")

    doc.add_heading("Governing Law", level=1)
    doc.add_paragraph("This agreement shall be governed by the laws of California.")

    doc.add_paragraph("IN WITNESS WHEREOF, the parties have executed this Agreement.")
    doc.add_paragraph("By: ____________________")
    doc.save(str(doc_path))

    try:
        parsed = parse_document(doc_path)
        result = await segment_document(parsed, enable_llm_refinement=False)

        assert result.total_substantive_clauses == 2
        assert len(result.clauses) == 2
        titles = [c.title for c in result.clauses]
        assert "Confidentiality Obligations" in titles
        assert "Governing Law" in titles

        # Preamble and signature block should be segregated
        assert result.preamble is not None
        assert "NON-DISCLOSURE AGREEMENT" in result.preamble
        assert result.signature_block is not None
        assert "IN WITNESS WHEREOF" in result.signature_block
    finally:
        doc_path.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_segment_text_based_pdf_with_signature() -> None:
    """Test PDF parsing and segmentation including sub-clauses and signature block."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)

    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=14)
        pdf.cell(text="SERVICES AGREEMENT PREAMBLE")
        pdf.ln(10)
        pdf.set_font("helvetica", size=12)
        pdf.cell(text="1. Limitation of Liability")
        pdf.ln(8)
        pdf.cell(text="1.1 Annual Fee Cap")
        pdf.ln(8)
        pdf.multi_cell(w=0, text="Total liability is capped at 12 months fees.")
        pdf.ln(8)
        pdf.cell(text="2. Termination")
        pdf.ln(8)
        pdf.cell(text="2.1 Termination for Convenience")
        pdf.ln(8)
        pdf.multi_cell(w=0, text="Either party may terminate on 30 days notice.")
        pdf.ln(10)
        pdf.cell(text="IN WITNESS WHEREOF, the parties sign below:")
        pdf.ln(8)
        pdf.cell(text="By: Authorized Agent")
        pdf.output(str(pdf_path))

        parsed = parse_document(pdf_path)
        result = await segment_document(parsed, enable_llm_refinement=False)

        assert result.total_substantive_clauses == 2
        c1 = result.clauses[0]
        assert c1.section_number == "1"
        assert "1.1 Annual Fee Cap" in c1.text

        c2 = result.clauses[1]
        assert c2.section_number == "2"
        assert "2.1 Termination for Convenience" in c2.text

        assert result.signature_block is not None
        assert "IN WITNESS WHEREOF" in result.signature_block
    finally:
        pdf_path.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_segment_with_definitions_section() -> None:
    """Ensure definitions sections are identified and separated from substantive clauses."""
    paragraphs = [
        ParsedParagraph(text="MASTER SERVICES AGREEMENT", is_heading=True, heading_level=0, order_index=0),
        ParsedParagraph(text="1. Definitions", is_heading=True, heading_level=1, order_index=1),
        ParsedParagraph(text="1.1 'Services' means the cloud software.", is_heading=False, order_index=2),
        ParsedParagraph(text="2. Limitation of Liability", is_heading=True, heading_level=1, order_index=3),
        ParsedParagraph(text="2.1 Liability is capped at fees paid.", is_heading=False, order_index=4),
    ]
    parsed_doc = ParsedDocument(contract_name="test.docx", file_type="docx", paragraphs=paragraphs)

    result = await segment_document(parsed_doc, enable_llm_refinement=False, include_definitions_in_clauses=False)

    # Definitions section should be separated
    assert result.definitions is not None
    assert result.definitions.section_number == "1"
    assert "Definitions" in result.definitions.title

    # Only substantive business clauses remain in clauses list
    assert result.total_substantive_clauses == 1
    assert result.clauses[0].section_number == "2"
    assert "Limitation of Liability" in result.clauses[0].title


@pytest.mark.anyio
async def test_llm_refinement_merge_mocked() -> None:
    """Test LLM refinement merging two accidentally split clauses with full text verification."""
    clauses = [
        Clause(id="C-001", section_number="1", title="Part 1", text="First half of liability terms.", clause_type=None),
        Clause(id="C-002", section_number="1", title="Part 2", text="Second half of liability terms.", clause_type=None),
        Clause(id="C-003", section_number="2", title="Indemnity", text="Indemnification clause terms.", clause_type=None),
    ]

    mock_plan = {
        "has_corrections": True,
        "merges": [
            {"clause_ids": ["C-001", "C-002"], "reason": "Both belong to Section 1"}
        ],
        "splits": [],
        "explanation": "Merged C-001 and C-002",
    }

    with patch("app.services.segment_refine.generate_structured_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_plan
        refined = await refine_clauses_with_llm(clauses, enable_refinement=True)

        assert len(refined) == 2
        assert refined[0].id == "C-001"
        assert "First half of liability terms." in refined[0].text
        assert "Second half of liability terms." in refined[0].text
        assert refined[1].id == "C-002"
        assert refined[1].title == "Indemnity"


@pytest.mark.anyio
async def test_llm_refinement_split_mocked() -> None:
    """Test LLM refinement splitting an accidentally merged clause with verbatim text preservation."""
    combined_text = (
        "Section 1. Liability Cap.\n"
        "Liability is capped at 12 months fees.\n\n"
        "Section 2. Consequential Damages.\n"
        "Neither party shall be liable for lost profits."
    )
    clauses = [
        Clause(id="C-001", section_number="1", title="Liability", text=combined_text, clause_type=None)
    ]

    mock_plan = {
        "has_corrections": True,
        "merges": [],
        "splits": [
            {
                "clause_id": "C-001",
                "split_after_text": "Liability is capped at 12 months fees.",
                "new_clause_title": "Consequential Damages",
                "reason": "Section 2 was merged into Section 1",
            }
        ],
        "explanation": "Split Section 2 from Section 1",
    }

    with patch("app.services.segment_refine.generate_structured_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_plan
        refined = await refine_clauses_with_llm(clauses, enable_refinement=True)

        assert len(refined) == 2
        assert refined[0].id == "C-001"
        assert "Section 1. Liability Cap." in refined[0].text
        assert refined[1].id == "C-002"
        assert "Section 2. Consequential Damages." in refined[1].text
        assert refined[1].title == "Consequential Damages"


@pytest.mark.anyio
async def test_llm_refinement_text_loss_fallback() -> None:
    """Ensure LLM refinement falls back to heuristic clauses if text verification fails."""
    clauses = [
        Clause(id="C-001", section_number="1", title="Original Title", text="Important contract terms.", clause_type=None)
    ]

    # Delimiter not found in text -> split skipped or text length altered
    mock_plan = {
        "has_corrections": True,
        "merges": [],
        "splits": [
            {
                "clause_id": "C-001",
                "split_after_text": "Non-existent delimiter string",
                "new_clause_title": "New Title",
            }
        ],
        "explanation": "Split on absent text",
    }

    with patch("app.services.segment_refine.generate_structured_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_plan
        refined = await refine_clauses_with_llm(clauses, enable_refinement=True)

        # Falls back to original clause unchanged
        assert len(refined) == 1
        assert refined[0].text == "Important contract terms."


@pytest.mark.anyio
async def test_llm_refinement_exception_fallback() -> None:
    """Ensure LLM refinement catches API exceptions and falls back without raising."""
    clauses = [
        Clause(id="C-001", section_number="1", title="Title", text="Contract clause text.", clause_type=None)
    ]

    with patch("app.services.segment_refine.generate_structured_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = RuntimeError("Gemini API connection error")
        refined = await refine_clauses_with_llm(clauses, enable_refinement=True)

        # Fallback to original clauses
        assert len(refined) == 1
        assert refined[0].id == "C-001"
        assert refined[0].text == "Contract clause text."
