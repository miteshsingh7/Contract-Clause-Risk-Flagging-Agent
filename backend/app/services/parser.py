"""Document parser service supporting .docx and text-based .pdf formats.

Preserves document structure including paragraph ordering, heading flags,
and section numbering text without performing OCR or flattening text.
"""

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Union

from docx import Document
from pypdf import PdfReader

from app.models.schemas import ParsedDocument, ParsedParagraph

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".docx", ".pdf"}

# Regex patterns indicating likely headings in plain text
HEADING_TEXT_PATTERNS = [
    # "Section 1", "Section 1.1", "Sec. 2", "Article IV", "Art. 3"
    re.compile(r"^(?:Section|Sec\.|Article|Art\.)\s*(\d{1,2}|[IVXLCDM]+)(?:[\.:\s\-]+(.*))?$", re.IGNORECASE),
    # Top-level numbered headings: "1.", "1.0", "1 ", followed by Title
    re.compile(r"^(\d{1,2})\.?\s+([A-Z][A-Za-z0-9\s,\-_'\"]{2,80})$"),
    # Sub-clause headings: "1.1", "1.2.3"
    re.compile(r"^(\d{1,2}\.\d{1,2}(?:\.\d+)*)\.?\s+(.*)$"),
    # Roman numeral headings: "I. Title", "II. Title"
    re.compile(r"^([IVXLCDM]+)\.\s+([A-Z][A-Za-z0-9\s,\-_'\"]{2,80})$"),
    # All caps short titles (e.g. "LIMITATION OF LIABILITY", "RECITALS")
    re.compile(r"^[A-Z0-9\s,\-:]{4,60}$"),
]


def _detect_heading_from_text(text: str) -> tuple[bool, Optional[int]]:
    """Determine whether a plain text line represents a heading and estimate its level."""
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False, None

    # Check top-level Section / Article
    m_sec = re.match(r"^(?:Section|Sec\.|Article|Art\.)\s*(\d{1,2}|[IVXLCDM]+)", stripped, re.IGNORECASE)
    if m_sec:
        # Check if it has a decimal point like "Section 1.1"
        if "." in m_sec.group(1):
            return True, 2
        return True, 1

    # Check sub-clause numbering: 1.1, 2.3.1
    m_sub = re.match(r"^(\d{1,2}\.\d{1,2}(?:\.\d+)*)", stripped)
    if m_sub:
        dots = m_sub.group(1).count(".")
        return True, 1 + dots

    # Check top-level numeric "1. Title"
    m_num = re.match(r"^(\d{1,2})\.?\s+[A-Z]", stripped)
    if m_num:
        return True, 1

    # Check roman numerals
    m_rom = re.match(r"^([IVXLCDM]+)\.\s+[A-Z]", stripped)
    if m_rom:
        return True, 1

    # All-caps short line
    if stripped.isupper() and len(stripped) <= 60 and not stripped.endswith("."):
        return True, 1

    return False, None


def _parse_docx(file_path: Path) -> ParsedDocument:
    """Parse a .docx document preserving paragraph order and heading styles."""
    try:
        doc = Document(str(file_path))
    except Exception as exc:
        raise ValueError(f"Failed to read DOCX file '{file_path.name}': {exc}") from exc

    paragraphs: List[ParsedParagraph] = []
    order = 0

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue

        style_name = p.style.name if p.style else "Normal"
        lower_style = style_name.lower()
        is_heading_style = "heading" in lower_style or "title" in lower_style
        heading_level = None

        if is_heading_style:
            match = re.search(r"heading\s*(\d+)", lower_style)
            if match:
                heading_level = int(match.group(1))
            elif "title" in lower_style:
                heading_level = 0
        else:
            # Check text-based patterns if style is not explicitly a Word Heading
            text_is_heading, text_level = _detect_heading_from_text(text)
            if text_is_heading:
                is_heading_style = True
                heading_level = text_level

        paragraphs.append(
            ParsedParagraph(
                text=text,
                style_name=style_name,
                is_heading=is_heading_style,
                heading_level=heading_level,
                order_index=order,
            )
        )
        order += 1

    if not paragraphs:
        raise ValueError(f"Document '{file_path.name}' is empty or contains no extractable text.")

    return ParsedDocument(
        contract_name=file_path.name,
        file_type="docx",
        file_path=str(file_path.resolve()),
        paragraphs=paragraphs,
    )


def _parse_pdf(file_path: Path) -> ParsedDocument:
    """Parse a text-based .pdf document without OCR, preserving paragraph structure."""
    try:
        reader = PdfReader(str(file_path))
        if reader.is_encrypted:
            raise ValueError(
                f"PDF document '{file_path.name}' is password-protected or encrypted. Decryption is not supported."
            )
    except Exception as exc:
        raise ValueError(f"Failed to read PDF file '{file_path.name}': {exc}") from exc

    if len(reader.pages) == 0:
        raise ValueError(f"PDF document '{file_path.name}' contains no pages.")

    # Extract raw text from each page
    raw_lines: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        for line in page_text.splitlines():
            trimmed = line.strip()
            if trimmed:
                raw_lines.append(trimmed)

    if not raw_lines:
        raise ValueError(
            f"PDF document '{file_path.name}' is empty or contains no extractable text "
            "(note: scanned/image-only PDFs require OCR which is not supported in MVP)."
        )

    # Group lines into paragraphs, breaking on headings or blank lines
    paragraphs: List[ParsedParagraph] = []
    order = 0
    current_chunk: List[str] = []

    for line in raw_lines:
        is_heading, level = _detect_heading_from_text(line)

        if is_heading:
            # Flush accumulated paragraph if any
            if current_chunk:
                joined = " ".join(current_chunk).strip()
                if joined:
                    c_is_h, c_lvl = _detect_heading_from_text(joined)
                    paragraphs.append(
                        ParsedParagraph(
                            text=joined,
                            style_name="Heading" if c_is_h else "Normal",
                            is_heading=c_is_h,
                            heading_level=c_lvl,
                            order_index=order,
                        )
                    )
                    order += 1
                current_chunk = []

            # Add heading line as its own paragraph
            paragraphs.append(
                ParsedParagraph(
                    text=line,
                    style_name=f"Heading {level}" if level else "Heading",
                    is_heading=True,
                    heading_level=level,
                    order_index=order,
                )
            )
            order += 1
        else:
            # Check if this line looks like the start of a new paragraph or sub-point
            starts_new = bool(re.match(r"^(?:\([a-z0-9]+\)|[a-z]\.|\d+\.)\s+", line))
            prev_ended = (
                current_chunk
                and (current_chunk[-1].endswith(".") or current_chunk[-1].endswith(":") or current_chunk[-1].endswith(";"))
            )

            if starts_new and prev_ended:
                # Flush previous paragraph
                joined = " ".join(current_chunk).strip()
                if joined:
                    paragraphs.append(
                        ParsedParagraph(
                            text=joined,
                            style_name="Normal",
                            is_heading=False,
                            heading_level=None,
                            order_index=order,
                        )
                    )
                    order += 1
                current_chunk = [line]
            else:
                current_chunk.append(line)

    # Flush any remaining text chunk
    if current_chunk:
        joined = " ".join(current_chunk).strip()
        if joined:
            c_is_h, c_lvl = _detect_heading_from_text(joined)
            paragraphs.append(
                ParsedParagraph(
                    text=joined,
                    style_name="Heading" if c_is_h else "Normal",
                    is_heading=c_is_h,
                    heading_level=c_lvl,
                    order_index=order,
                )
            )
            order += 1

    if not paragraphs:
        raise ValueError(f"PDF document '{file_path.name}' is empty or contains no extractable text.")

    return ParsedDocument(
        contract_name=file_path.name,
        file_type="pdf",
        file_path=str(file_path.resolve()),
        paragraphs=paragraphs,
    )


def parse_document(file_path: Union[str, Path]) -> ParsedDocument:
    """Parse a contract document (.docx or .pdf) into a structured ParsedDocument.

    Args:
        file_path: Path to the target contract document.

    Returns:
        ParsedDocument containing the contract name, file type, and ordered paragraphs.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        ValueError: If file format is unsupported or the document contains no extractable text.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Contract file not found at: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format '{path.suffix}'. "
            f"Supported formats are: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if suffix == ".docx":
        return _parse_docx(path)
    elif suffix == ".pdf":
        return _parse_pdf(path)
    else:
        raise ValueError(f"Unhandled file format: {suffix}")
