"""Tests for the document parser service (DOCX and text-based PDF)."""

import tempfile
from pathlib import Path
import pytest
from docx import Document
from fpdf import FPDF

from app.services.parser import parse_document


def test_parse_unsupported_extension() -> None:
    """Ensure unsupported file formats raise clear ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
        with pytest.raises(ValueError, match="Unsupported file format"):
            parse_document(tmp.name)


def test_parse_nonexistent_file() -> None:
    """Ensure nonexistent file paths raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="Contract file not found"):
        parse_document("non_existent_contract.docx")


def test_parse_empty_docx() -> None:
    """Ensure empty document raises clear ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    doc = Document()
    doc.save(str(tmp_path))

    try:
        with pytest.raises(ValueError, match="empty or contains no extractable text"):
            parse_document(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def test_parse_docx_sample() -> None:
    """Test parsing of sample_contract_compliant.docx."""
    sample_path = Path("backend/data/samples/sample_contract_compliant.docx")
    assert sample_path.exists(), "Sample contract must exist"

    parsed = parse_document(sample_path)
    assert parsed.contract_name == "sample_contract_compliant.docx"
    assert parsed.file_type == "docx"
    assert parsed.total_paragraphs >= 20

    # Ensure paragraphs preserve order indices
    for idx, p in enumerate(parsed.paragraphs):
        assert p.order_index == idx
        assert len(p.text) > 0

    # Ensure headings were identified
    headings = [p for p in parsed.paragraphs if p.is_heading]
    assert len(headings) >= 10


def test_parse_text_based_pdf() -> None:
    """Test generating and parsing a text-based PDF without OCR."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)

    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("helvetica", size=14)
        pdf.cell(text="CONFIDENTIALITY AGREEMENT")
        pdf.ln(10)
        pdf.set_font("helvetica", size=12)
        pdf.cell(text="1. Non-Disclosure Obligations")
        pdf.ln(8)
        pdf.multi_cell(w=0, text="Recipient shall hold proprietary technical data strictly confidential.")
        pdf.ln(8)
        pdf.cell(text="2. Term and Governing Law")
        pdf.ln(8)
        pdf.multi_cell(w=0, text="This Agreement terminates in three years and is governed by Delaware law.")
        pdf.output(str(pdf_path))

        parsed = parse_document(pdf_path)
        assert parsed.file_type == "pdf"
        assert parsed.contract_name == pdf_path.name
        assert parsed.total_paragraphs >= 4

        texts = [p.text for p in parsed.paragraphs]
        assert any("CONFIDENTIALITY AGREEMENT" in t for t in texts)
        assert any("1. Non-Disclosure Obligations" in t for t in texts)
        assert any("2. Term and Governing Law" in t for t in texts)
    finally:
        pdf_path.unlink(missing_ok=True)


def test_parse_encrypted_pdf() -> None:
    """Ensure encrypted PDF raises clear descriptive ValueError."""
    from pypdf import PdfWriter
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)

    try:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt("secret_pass")
        with open(pdf_path, "wb") as f:
            writer.write(f)

        with pytest.raises(ValueError, match="password-protected or encrypted"):
            parse_document(pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)


def test_parse_corrupt_files() -> None:
    """Ensure corrupted DOCX and PDF files raise clear descriptive ValueError."""
    # Corrupt DOCX
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        docx_path = Path(tmp.name)
        docx_path.write_bytes(b"not a valid zip or docx content")

    try:
        with pytest.raises(ValueError, match="Failed to read DOCX file"):
            parse_document(docx_path)
    finally:
        docx_path.unlink(missing_ok=True)

    # Corrupt PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)
        pdf_path.write_bytes(b"not a valid pdf header")

    try:
        with pytest.raises(ValueError, match="Failed to read PDF file"):
            parse_document(pdf_path)
    finally:
        pdf_path.unlink(missing_ok=True)

