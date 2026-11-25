"""Heuristic contract clause segmenter.

Splits parsed contracts into distinct substantive clauses based on numbering
hierarchies and heading styles, while separating non-substantive elements
(preamble, recitals, definitions, and signature blocks).

Rule: A clause = one top-level numbered section INCLUDING all its sub-clauses
(e.g., Section 1 includes 1.1, 1.2), maintaining a complete unit of legal meaning.
"""

import logging
import re
from typing import List, Optional, Tuple

from app.models.schemas import Clause, ParsedDocument, ParsedParagraph, SegmentationResult
from app.services.segment_refine import refine_clauses_with_llm

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Regex Patterns for Clause & Section Detection
# ------------------------------------------------------------------------------

# Top-level Section or Article: "Section 1.", "Section 1:", "Article II.", "Sec. 3"
# Note: Negative lookahead ensures we do NOT match "Section 1.1" or "Sec. 2.3"
RE_SECTION_ARTICLE = re.compile(
    r"^(?:Section|Sec\.|Article|Art\.)\s*(\d{1,2}|[IVXLCDM]+)(?!\.\d)[\.:\s\-]+(.*)$",
    re.IGNORECASE,
)

# Numeric top-level heading: "1.", "1.0", "1 ", followed by capital letter title
# Negative lookahead (?!\.\d) ensures "1.1", "1.2" are NOT matched as top-level
RE_NUMERIC_TOP_LEVEL = re.compile(
    r"^(\d{1,2})(?:\.0)?\.?\s+([A-Z][A-Za-z0-9\s,\-_'\"]{2,80})$"
)

# Roman numeral top-level heading: "I. Title", "IV. Title"
RE_ROMAN_TOP_LEVEL = re.compile(
    r"^([IVXLCDM]+)\.\s+([A-Z][A-Za-z0-9\s,\-_'\"]{2,80})$"
)

# Sub-clause patterns (must NOT start a new clause; appended to active parent)
RE_SUB_CLAUSE_DECIMAL = re.compile(
    r"^(?:(?:Section|Sec\.)\s*)?(\d{1,2}\.\d{1,2}(?:\.\d+)*)\.?\s+(.*)$",
    re.IGNORECASE,
)
RE_SUB_CLAUSE_LETTERED = re.compile(
    r"^(?:\(([a-z0-9]+)\)|([a-z0-9])\.)\s+(.*)$",
    re.IGNORECASE,
)

# Signature block start markers (unanchored to match inside joined lines)
RE_SIGNATURE_START = re.compile(
    r"\b(?:IN\s+WITNESS\s+WHEREOF|ACCEPTED\s+AND\s+AGREED|AGREED\s+AND\s+ACCEPTED|"
    r"EXECUTED\s+(?:AS\s+AN\s+AGREEMENT|BY\s+THE\s+PARTIES)|"
    r"THE\s+PARTIES\s+HERETO\s+HAVE\s+EXECUTED|SIGNATURES|SIGNATURE\s+PAGE)\b",
    re.IGNORECASE,
)

# Definitions section title pattern
RE_DEFINITIONS_TITLE = re.compile(
    r"^(?:(?:Section|Article|\d+)\.?\s*)?Definitions(?:\s+and\s+Interpretation)?\b",
    re.IGNORECASE,
)


def _is_top_level_section(
    paragraph: ParsedParagraph,
    require_numbering: bool = False,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Check if a paragraph represents a new top-level section/clause.

    Args:
        paragraph: ParsedParagraph to evaluate.
        require_numbering: If True, only accepts sections that have explicit numbering.

    Returns:
        (is_top_level, section_number, title)
    """
    text = paragraph.text.strip()

    # Exclude obvious non-clause headers
    lower_text = text.lower()
    if lower_text.endswith("preamble") or "recitals" in lower_text or lower_text.startswith("in witness"):
        return False, None, None

    # Rule 1: Explicit Section / Article keyword (e.g. "Section 1. Limitation of Liability")
    match_sec = RE_SECTION_ARTICLE.match(text)
    if match_sec:
        sec_num = match_sec.group(1).strip()
        title = match_sec.group(2).strip().rstrip(".:")
        return True, sec_num, title

    # Rule 2: Top-level numeric with title (e.g. "1. Limitation of Liability")
    # Must NOT be a sub-clause like 1.1 or 1.2
    if not RE_SUB_CLAUSE_DECIMAL.match(text):
        match_num = RE_NUMERIC_TOP_LEVEL.match(text)
        if match_num:
            sec_num = match_num.group(1).strip()
            title = match_num.group(2).strip().rstrip(".:")
            return True, sec_num, title

        # Roman numerals (e.g. "I. Limitation of Liability")
        match_rom = RE_ROMAN_TOP_LEVEL.match(text)
        if match_rom:
            sec_num = match_rom.group(1).strip()
            title = match_rom.group(2).strip().rstrip(".:")
            return True, sec_num, title

    # If explicit numbering is required, do not match unnumbered headings
    if require_numbering:
        return False, None, None

    # Rule 3: Word Heading 1 style with title-like text that is not document title
    if paragraph.is_heading and paragraph.heading_level == 1:
        # Check if it has numbering
        match_num2 = re.match(r"^(\d{1,2})[\.:\s\-]+(.*)$", text)
        if match_num2 and not RE_SUB_CLAUSE_DECIMAL.match(text):
            return True, match_num2.group(1).strip(), match_num2.group(2).strip().rstrip(".:")
        # Check if it is a capitalized heading (>= 4 chars, <= 80 chars)
        if (
            len(text) <= 80
            and not lower_text.startswith("master")
            and not lower_text.startswith("agreement")
            and not lower_text.startswith("contract")
        ):
            return True, None, text.rstrip(".:")

    return False, None, None


def _is_signature_marker(text: str) -> bool:
    """Check if text denotes the beginning of the execution/signature block."""
    stripped = text.strip()
    if RE_SIGNATURE_START.search(stripped):
        return True
    # Look for execution lines like "By: _________" or "Name: ______ Title: ______"
    if stripped.startswith("By:") or stripped.startswith("Signature:") or stripped.startswith("Authorized Signature:"):
        return True
    return False


def _document_has_numbering(paragraphs: List[ParsedParagraph]) -> bool:
    """Determine whether the document contains standard numbered sections."""
    count = 0
    for p in paragraphs:
        is_top, sec_num, _ = _is_top_level_section(p, require_numbering=True)
        if is_top and sec_num is not None:
            count += 1
            if count >= 2:
                return True
    return False


def _segment_numbered_contract(
    contract_name: str,
    paragraphs: List[ParsedParagraph],
    include_definitions_in_clauses: bool = False,
) -> SegmentationResult:
    """Segment a standard contract with numbered sections and sub-clauses."""
    preamble_lines: List[str] = []
    signature_lines: List[str] = []
    clauses: List[Clause] = []
    definitions_clause: Optional[Clause] = None

    current_clause_id_idx = 1
    current_sec_num: Optional[str] = None
    current_title: Optional[str] = None
    current_clause_paragraphs: List[str] = []
    in_signature_block = False
    in_preamble = True

    for p in paragraphs:
        text = p.text.strip()
        if not text:
            continue

        # Check for signature block transition
        sig_match = RE_SIGNATURE_START.search(text)
        if sig_match or text.startswith("By:") or text.startswith("Signature:") or text.startswith("Authorized Signature:"):
            in_signature_block = True
            if sig_match:
                split_idx = sig_match.start()
                before_sig = text[:split_idx].strip()
                sig_text = text[split_idx:].strip()
            else:
                before_sig = ""
                sig_text = text

            if before_sig:
                current_clause_paragraphs.append(before_sig)

            # Finalize open clause
            if current_clause_paragraphs and (current_sec_num is not None or current_title is not None):
                full_text = "\n\n".join(current_clause_paragraphs).strip()
                clause_obj = Clause(
                    id=f"C-{current_clause_id_idx:03d}",
                    section_number=current_sec_num,
                    title=current_title,
                    text=full_text,
                    clause_type=None,
                )
                if RE_DEFINITIONS_TITLE.search(current_title or ""):
                    definitions_clause = clause_obj
                    if include_definitions_in_clauses:
                        clauses.append(clause_obj)
                else:
                    clauses.append(clause_obj)
                    current_clause_id_idx += 1
                current_clause_paragraphs = []
                current_sec_num = None
                current_title = None

            if sig_text:
                signature_lines.append(sig_text)
            continue

        if in_signature_block:
            signature_lines.append(text)
            continue

        # Check for new top-level section (requiring explicit section numbering)
        is_top, sec_num, title = _is_top_level_section(p, require_numbering=True)

        if is_top:
            # We have encountered the first top-level section -> end of preamble
            in_preamble = False

            # Finalize previous clause if open
            if current_clause_paragraphs and (current_sec_num is not None or current_title is not None):
                full_text = "\n\n".join(current_clause_paragraphs).strip()
                clause_obj = Clause(
                    id=f"C-{current_clause_id_idx:03d}",
                    section_number=current_sec_num,
                    title=current_title,
                    text=full_text,
                    clause_type=None,
                )
                if RE_DEFINITIONS_TITLE.search(current_title or ""):
                    definitions_clause = clause_obj
                    if include_definitions_in_clauses:
                        clauses.append(clause_obj)
                else:
                    clauses.append(clause_obj)
                    current_clause_id_idx += 1

            # Start new top-level clause
            current_sec_num = sec_num
            current_title = title
            current_clause_paragraphs = [text]

        else:
            if in_preamble:
                preamble_lines.append(text)
            else:
                # Sub-clause or body paragraph -> append to current active clause
                current_clause_paragraphs.append(text)

    # Finalize last clause if any remaining
    if current_clause_paragraphs and (current_sec_num is not None or current_title is not None):
        full_text = "\n\n".join(current_clause_paragraphs).strip()
        clause_obj = Clause(
            id=f"C-{current_clause_id_idx:03d}",
            section_number=current_sec_num,
            title=current_title,
            text=full_text,
            clause_type=None,
        )
        if RE_DEFINITIONS_TITLE.search(current_title or ""):
            definitions_clause = clause_obj
            if include_definitions_in_clauses:
                clauses.append(clause_obj)
        else:
            clauses.append(clause_obj)

    preamble_text = "\n\n".join(preamble_lines).strip() if preamble_lines else None
    sig_text = "\n\n".join(signature_lines).strip() if signature_lines else None

    return SegmentationResult(
        contract_name=contract_name,
        clauses=clauses,
        preamble=preamble_text,
        definitions=definitions_clause,
        signature_block=sig_text,
        total_substantive_clauses=len(clauses),
    )


def _is_document_title(text: str, style_name: Optional[str] = None, heading_level: Optional[int] = None) -> bool:
    """Check if a heading represents the overall contract title rather than a clause."""
    if heading_level == 0:
        return True
    lower = text.lower()
    if style_name and "title" in style_name.lower():
        return True
    if any(keyword in lower for keyword in ["agreement", "contract", "nda", "terms of service", "memorandum"]):
        return True
    return False


def _segment_unnumbered_contract(
    contract_name: str,
    paragraphs: List[ParsedParagraph],
) -> SegmentationResult:
    """Fallback segmenter for contracts without numbering (using heading styles or paragraph groupings)."""
    preamble_lines: List[str] = []
    signature_lines: List[str] = []
    clauses: List[Clause] = []

    # Identify true clause headings (excluding document titles and recitals)
    heading_indices = [
        idx for idx, p in enumerate(paragraphs)
        if (p.is_heading or (p.style_name and "heading" in p.style_name.lower()))
        and not _is_document_title(p.text, p.style_name, p.heading_level)
    ]

    in_signature = False
    clause_idx = 1

    if heading_indices:
        # Heading-style fallback
        first_heading_idx = heading_indices[0]
        preamble_lines = [p.text for p in paragraphs[:first_heading_idx] if p.text.strip()]

        current_title: Optional[str] = None
        current_paras: List[str] = []

        for p in paragraphs[first_heading_idx:]:
            text = p.text.strip()
            if not text:
                continue

            sig_match = RE_SIGNATURE_START.search(text)
            if sig_match or text.startswith("By:") or text.startswith("Signature:") or text.startswith("Authorized Signature:"):
                in_signature = True
                if sig_match:
                    split_idx = sig_match.start()
                    before_sig = text[:split_idx].strip()
                    sig_text = text[split_idx:].strip()
                else:
                    before_sig = ""
                    sig_text = text

                if before_sig:
                    current_paras.append(before_sig)

                if current_paras:
                    clauses.append(
                        Clause(
                            id=f"C-{clause_idx:03d}",
                            section_number=f"Sec {clause_idx}",
                            title=current_title or f"Clause {clause_idx}",
                            text="\n\n".join(current_paras).strip(),
                            clause_type=None,
                        )
                    )
                    clause_idx += 1
                    current_paras = []
                    current_title = None

                if sig_text:
                    signature_lines.append(sig_text)
                continue

            if in_signature:
                signature_lines.append(text)
                continue

            # If this paragraph is a heading
            if p.is_heading or (p.style_name and "heading" in p.style_name.lower()):
                # Flush previous
                if current_paras:
                    clauses.append(
                        Clause(
                            id=f"C-{clause_idx:03d}",
                            section_number=f"Sec {clause_idx}",
                            title=current_title or f"Clause {clause_idx}",
                            text="\n\n".join(current_paras).strip(),
                            clause_type=None,
                        )
                    )
                    clause_idx += 1
                current_title = text
                current_paras = [text]
            else:
                current_paras.append(text)

        if current_paras:
            clauses.append(
                Clause(
                    id=f"C-{clause_idx:03d}",
                    section_number=f"Sec {clause_idx}",
                    title=current_title or f"Clause {clause_idx}",
                    text="\n\n".join(current_paras).strip(),
                    clause_type=None,
                )
            )

    else:
        # Paragraph grouping fallback: group substantive paragraphs into logical clause blocks
        substantive_paras = []
        for p in paragraphs:
            text = p.text.strip()
            if not text:
                continue
            if _is_signature_marker(text):
                in_signature = True
            if in_signature:
                signature_lines.append(text)
            else:
                substantive_paras.append(text)

        # First paragraph is preamble if it resembles title/recital
        if substantive_paras and (
            "agreement" in substantive_paras[0].lower() or "party" in substantive_paras[0].lower()
        ):
            preamble_lines = [substantive_paras.pop(0)]

        for p_text in substantive_paras:
            first_sentence = p_text.split(".")[0].strip()
            title = first_sentence[:60] if len(first_sentence) <= 60 else f"Clause {clause_idx}"
            clauses.append(
                Clause(
                    id=f"C-{clause_idx:03d}",
                    section_number=f"Para {clause_idx}",
                    title=title,
                    text=p_text,
                    clause_type=None,
                )
            )
            clause_idx += 1

    preamble_text = "\n\n".join(preamble_lines).strip() if preamble_lines else None
    sig_text = "\n\n".join(signature_lines).strip() if signature_lines else None

    return SegmentationResult(
        contract_name=contract_name,
        clauses=clauses,
        preamble=preamble_text,
        definitions=None,
        signature_block=sig_text,
        total_substantive_clauses=len(clauses),
    )


async def segment_document(
    parsed_document: ParsedDocument,
    enable_llm_refinement: Optional[bool] = None,
    include_definitions_in_clauses: bool = False,
) -> SegmentationResult:
    """Segment a parsed contract into clauses and non-substantive components.

    Executes heuristic boundary detection first, and conditionally refines
    the boundaries via an LLM pass if enabled.

    Args:
        parsed_document: ParsedDocument object containing ordered paragraphs.
        enable_llm_refinement: Optional flag to override config setting for LLM refinement.
        include_definitions_in_clauses: If True, includes definitions in the substantive clauses list.

    Returns:
        SegmentationResult containing clauses, preamble, definitions, and signature block.
    """
    paragraphs = parsed_document.paragraphs

    if not paragraphs:
        return SegmentationResult(
            contract_name=parsed_document.contract_name,
            clauses=[],
            preamble=None,
            definitions=None,
            signature_block=None,
            total_substantive_clauses=0,
        )

    # 1. Choose segmenter based on document numbering presence
    if _document_has_numbering(paragraphs):
        result = _segment_numbered_contract(
            contract_name=parsed_document.contract_name,
            paragraphs=paragraphs,
            include_definitions_in_clauses=include_definitions_in_clauses,
        )
    else:
        logger.info(
            "No standard section numbering found in '%s'; using heading/paragraph fallback.",
            parsed_document.contract_name,
        )
        result = _segment_unnumbered_contract(
            contract_name=parsed_document.contract_name,
            paragraphs=paragraphs,
        )

    # 2. Conditionally apply LLM refinement pass
    if result.clauses:
        refined_clauses = await refine_clauses_with_llm(
            clauses=result.clauses,
            enable_refinement=enable_llm_refinement,
        )
        result.clauses = refined_clauses
        result.total_substantive_clauses = len(refined_clauses)

    return result
