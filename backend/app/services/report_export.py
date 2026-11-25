"""Export service for ReviewReport objects into Markdown, DOCX, and JSON formats.

All exports:
- Prominently feature the mandatory advisory legal disclaimer.
- Clearly delineate AI advisory suggestions from approved reviewer decisions.
- Render word-level redline diffs (strikethrough / underline in DOCX, markup in Markdown).
"""

from datetime import datetime
import io
import json
import logging
from typing import Any, Dict, List

import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor

from app.models.schemas import (
    DecisionStatus,
    DiffType,
    ReportClauseItem,
    ReviewDecisionRecord,
    ReviewReport,
    RiskLevel,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# 1. Markdown Export
# ------------------------------------------------------------------------------


def _render_markdown_diff(segments: List[Any]) -> str:
    """Format word diff segments as readable Markdown."""
    if not segments:
        return "*(No redline suggested — clause conforms to standard position)*"

    parts = []
    for s in segments:
        stype = s.type if hasattr(s, "type") else s.get("type")
        stype_val = stype.value if hasattr(stype, "value") else str(stype)
        text = s.text if hasattr(s, "text") else s.get("text", "")

        if stype_val == DiffType.EQUAL.value:
            parts.append(text)
        elif stype_val == DiffType.DELETE.value:
            parts.append(f"~~{text}~~")
        elif stype_val == DiffType.INSERT.value:
            parts.append(f"**{text}**")

    return "".join(parts)


def report_to_markdown(report: ReviewReport) -> str:
    """Generate clean, publication-ready GitHub-Flavored Markdown for the review report."""
    md: List[str] = []

    # Title & Legal Disclaimer
    md.append(f"# Contract Review and Redline Report: {report.contract_name}")
    md.append("")
    md.append("> **IMPORTANT LEGAL NOTICE: ADVISORY ONLY**  ")
    md.append(f"> {report.disclaimer}")
    md.append("")
    md.append("---")
    md.append("")

    # Metadata Header
    md.append("## 1. Review Overview")
    md.append("")
    md.append(f"- **Contract Name:** `{report.contract_name}`")
    md.append(f"- **Review ID:** `{report.review_id or report.report_id}`")
    md.append(f"- **Uploaded At:** {report.uploaded_at or 'N/A'}")
    md.append(f"- **Finalized At:** {report.finalized_at or 'N/A'}")
    reviewers_str = ", ".join(report.reviewers) if report.reviewers else "None recorded"
    md.append(f"- **Legal Reviewers Involved:** {reviewers_str}")
    md.append(f"- **Total Substantive Clauses:** {report.total_clauses}")
    md.append("")

    # Executive Summary Table
    md.append("## 2. Executive Summary")
    md.append("")
    md.append(report.summary or "")
    md.append("")
    md.append("### Risk Assessment Breakdown")
    md.append("")
    md.append("| Risk Level | Count | Share |")
    md.append("|---|---:|---:|")
    total = max(report.total_clauses, 1)
    md.append(f"| **Acceptable** | {report.acceptable_count} | {report.acceptable_count / total * 100:.1f}% |")
    md.append(f"| **Needs Negotiation** | {report.needs_negotiation_count} | {report.needs_negotiation_count / total * 100:.1f}% |")
    md.append(f"| **Unacceptable** | {report.unacceptable_count} | {report.unacceptable_count / total * 100:.1f}% |")
    md.append(f"| *Flagged for Human Review* | *{report.needs_human_review_count}* | *{report.needs_human_review_count / total * 100:.1f}%* |")
    md.append("")

    md.append("### Human Review Decisions")
    md.append("")
    md.append("| Decision Status | Count |")
    md.append("|---|---:|")
    md.append(f"| **Approved** | {report.approved_count} |")
    md.append(f"| **Edited** | {report.edited_count} |")
    md.append(f"| **Rejected** | {report.rejected_count} |")
    md.append("")

    # Highest Risk Clauses
    if report.highest_risk_clauses:
        md.append("### Priority Attention Clauses (Highest Risk)")
        md.append("")
        md.append("| Section | Title | Risk Level | Category | Human Review Flag |")
        md.append("|---|---|---|---|---|")
        for h in report.highest_risk_clauses:
            sec = h.get("section_number") or h.get("clause_id")
            title = h.get("title") or "Untitled"
            risk = h.get("risk_level")
            ctype = h.get("clause_type")
            needs_rev = "Yes" if h.get("needs_human_review") else "No"
            md.append(f"| **{sec}** | {title} | `{risk}` | `{ctype}` | {needs_rev} |")
        md.append("")

    # Contract-Level Findings: Missing Clauses
    md.append("## 3. Contract-Level Findings (Missing Playbook Clauses)")
    md.append("")
    if report.missing_clause_types:
        md.append("> **INFORMATIONAL NOTICE:** The following standard company playbook clause types were **not detected** in the evaluated document:")
        md.append("")
        for missing in report.missing_clause_types:
            clean_name = missing.replace("_", " ").title()
            md.append(f"- **{clean_name}** (`{missing}`)")
        md.append("")
        md.append("Legal counsel should assess whether omissions should be requested as affirmative additions.")
    else:
        md.append("All 10 standard corporate negotiation playbook clause types were detected in the agreement.")
    md.append("")

    # Resulting Clause Text Rule Note
    md.append("---")
    md.append("")
    md.append("## 4. Per-Clause Risk Analysis & Approved Language")
    md.append("")
    md.append(f"> **NOTE ON RESULTING LANGUAGE:** {report.resulting_text_rule_note}")
    md.append("")

    # Per-Clause Breakdown
    for idx, item in enumerate(report.clauses, start=1):
        sec_label = f"Section {item.section_number}" if item.section_number else f"Clause {item.clause_id}"
        title_label = item.title or "Untitled Clause"
        md.append(f"### {idx}. {sec_label}: {title_label}")
        md.append("")

        # Clause badges
        risk_badge = f"**Risk:** `{item.risk_level.value}`"
        type_badge = f"**Type:** `{item.clause_type}`"
        conf_badge = f"**Confidence:** `{item.confidence:.2f}`"
        review_flag = "**Flagged for Review:** `Yes`" if item.needs_human_review else "**Flagged for Review:** `No`"
        md.append(f"{risk_badge} | {type_badge} | {conf_badge} | {review_flag}")
        if item.review_reason:
            md.append(f"*Review Trigger: {item.review_reason}*")
        md.append("")

        # Original Text
        md.append("#### Original Contract Text")
        md.append("```text")
        md.append(item.original_text.strip())
        md.append("```")
        md.append("")

        # AI Analysis & Policy Grounding
        md.append("#### AI Advisory Analysis & Policy Grounding")
        md.append(f"**Explanation:** {item.explanation}")
        md.append("")
        if item.cited_rules:
            md.append("**Cited Corporate Playbook Rules:**")
            for r in item.cited_rules:
                md.append(f"- **[{r.rule_id}] {r.title}**")
                md.append(f"  - *Standard Position:* {r.standard_position}")
                md.append(f"  - *Acceptable Fallback:* {r.acceptable_fallback}")
                if r.unacceptable_triggers:
                    md.append(f"  - *Unacceptable Triggers:* {', '.join(r.unacceptable_triggers)}")
            md.append("")

        # AI-Suggested Redline (Advisory)
        md.append("#### AI-Suggested Redline *(Advisory Recommendation)*")
        if item.suggested_redline:
            md.append(f"**Proposed Text:** {item.suggested_redline}")
            md.append("")
            md.append("**Visual Redline Diff:**")
            md.append(_render_markdown_diff(item.redline_diff))
        else:
            md.append("*(No redline suggested — clause complies with standard position)*")
        md.append("")

        # Reviewer Decision (Approved Action)
        md.append("#### Legal Reviewer Decision *(Official Approval)*")
        if item.decision:
            d = item.decision
            status_val = d.status.value.upper() if hasattr(d.status, "value") else str(d.status).upper()
            md.append(f"- **Decision:** `{status_val}`")
            md.append(f"- **Reviewer:** {d.reviewer_name}")
            md.append(f"- **Decided At:** {d.decided_at}")
            if d.reviewer_note:
                md.append(f"- **Reviewer Note:** {d.reviewer_note}")
            if d.final_text:
                md.append(f"- **Reviewer Edited Final Text:** `{d.final_text}`")
        else:
            md.append("- **Decision:** *(Not required — clause evaluated as Acceptable)*")
        md.append("")

        # Resulting Clause Text
        md.append("#### Resulting Clause Text")
        md.append(f"*Source: {item.resulting_text_source}*")
        md.append("```text")
        md.append(item.resulting_text.strip())
        md.append("```")
        md.append("")
        md.append("---")
        md.append("")

    # Appendix: Decision Audit Trail
    md.append("## 5. Appendix: Complete Decision Audit Trail")
    md.append("")
    md.append("Complete, immutable chronological log of all reviewer decisions submitted for this contract:")
    md.append("")
    md.append("| Clause ID | Decision # | Timestamp | Reviewer | Status | Note | Modified Text Preview |")
    md.append("|---|---:|---|---|---|---|---|")

    has_decisions = False
    for cid, history in report.appendix_decision_history.items():
        for record in history:
            has_decisions = True
            note = (record.reviewer_note or "—").replace("|", "/")
            final_preview = (record.final_text[:40] + "...") if record.final_text else "—"
            final_preview = final_preview.replace("|", "/")
            stat = record.status.value if hasattr(record.status, "value") else str(record.status)
            md.append(f"| `{cid}` | {record.decision_id} | {record.decided_at[:19]} | {record.reviewer_name} | `{stat}` | {note} | {final_preview} |")

    if not has_decisions:
        md.append("| — | — | — | — | No decisions recorded | — | — |")
    md.append("")

    # Bottom Disclaimer
    md.append("---")
    md.append("> **IMPORTANT LEGAL NOTICE: ADVISORY ONLY**  ")
    md.append(f"> {report.disclaimer}")
    md.append("")

    return "\n".join(md)


# ------------------------------------------------------------------------------
# 2. DOCX Export
# ------------------------------------------------------------------------------


def report_to_docx(report: ReviewReport) -> bytes:
    """Generate a clean Microsoft Word (.docx) document with visual redline diffs."""
    doc = docx.Document()

    # Set document margins
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Document Title
    title_p = doc.add_paragraph()
    title_run = title_p.add_run(f"Contract Review & Redline Report\n{report.contract_name}")
    title_run.font.size = Pt(20)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(30, 41, 59)

    # Advisory Notice Callout
    callout_table = doc.add_table(rows=1, cols=1)
    callout_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = callout_table.cell(0, 0)
    cp = cell.paragraphs[0]
    c_bold = cp.add_run("IMPORTANT LEGAL NOTICE: ADVISORY ONLY\n")
    c_bold.font.bold = True
    c_bold.font.size = Pt(10)
    c_bold.font.color.rgb = RGBColor(180, 83, 9)
    c_text = cp.add_run(report.disclaimer)
    c_text.font.size = Pt(9.5)
    c_text.font.italic = True
    doc.add_paragraph()

    # Metadata Paragraph
    meta_p = doc.add_paragraph()
    meta_p.add_run(f"Report ID: {report.report_id}  |  Review ID: {report.review_id or 'N/A'}\n")
    meta_p.add_run(f"Uploaded: {report.uploaded_at or 'N/A'}  |  Finalized: {report.finalized_at or 'N/A'}\n")
    revs = ", ".join(report.reviewers) if report.reviewers else "None recorded"
    meta_p.add_run(f"Legal Reviewers: {revs}")
    meta_p.runs[0].font.size = Pt(9.5)

    doc.add_heading("1. Executive Summary", level=1)
    sum_p = doc.add_paragraph(report.summary or "")
    sum_p.runs[0].font.size = Pt(10)

    # Risk Summary Table
    table = doc.add_table(rows=4, cols=3)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"

    headers = ["Risk Level", "Clause Count", "Percentage"]
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.paragraphs[0].add_run(h).font.bold = True

    total = max(report.total_clauses, 1)
    row_data = [
        ("Acceptable", str(report.acceptable_count), f"{report.acceptable_count / total * 100:.1f}%"),
        ("Needs Negotiation", str(report.needs_negotiation_count), f"{report.needs_negotiation_count / total * 100:.1f}%"),
        ("Unacceptable", str(report.unacceptable_count), f"{report.unacceptable_count / total * 100:.1f}%"),
    ]
    for row_idx, data in enumerate(row_data, start=1):
        for col_idx, val in enumerate(data):
            cell = table.cell(row_idx, col_idx)
            cell.paragraphs[0].add_run(val)

    doc.add_paragraph()

    # Contract Level Findings (Missing Clauses)
    doc.add_heading("2. Contract-Level Findings (Missing Clauses)", level=1)
    if report.missing_clause_types:
        mp = doc.add_paragraph()
        mp_run = mp.add_run("The following standard playbook clause types were omitted from this contract:\n")
        mp_run.font.bold = True
        for missing in report.missing_clause_types:
            doc.add_paragraph(f"• {missing.replace('_', ' ').title()} ({missing})", style="List Bullet")
    else:
        doc.add_paragraph("All 10 standard corporate negotiation playbook clause types were detected.")

    doc.add_paragraph()

    # Per-Clause Detailed Findings
    doc.add_heading("3. Clause-by-Clause Analysis & Redlines", level=1)
    rule_note_p = doc.add_paragraph()
    r_run = rule_note_p.add_run(f"NOTE: {report.resulting_text_rule_note}")
    r_run.font.italic = True
    r_run.font.size = Pt(9.5)

    for item in report.clauses:
        sec = f"Section {item.section_number}" if item.section_number else f"Clause {item.clause_id}"
        heading_text = f"{sec}: {item.title or 'Untitled Clause'}"
        doc.add_heading(heading_text, level=2)

        # Meta info
        cp = doc.add_paragraph()
        cp.add_run(f"Risk Level: {item.risk_level.value}  |  Category: {item.clause_type}  |  Confidence: {item.confidence:.2f}\n")
        if item.needs_human_review:
            flag_run = cp.add_run(f"Flagged for Review: Yes ({item.review_reason or 'Policy criteria'})\n")
            flag_run.font.color.rgb = RGBColor(192, 0, 0)

        # Original text
        doc.add_heading("Original Contract Text", level=3)
        orig_p = doc.add_paragraph(item.original_text)
        orig_p.runs[0].font.size = Pt(9.5)

        # AI-Suggested Redline Diff
        doc.add_heading("AI-Suggested Redline (Advisory)", level=3)
        if item.redline_diff:
            diff_p = doc.add_paragraph()
            for seg in item.redline_diff:
                stype = seg.type if hasattr(seg, "type") else seg.get("type")
                stype_val = stype.value if hasattr(stype, "value") else str(stype)
                stext = seg.text if hasattr(seg, "text") else seg.get("text", "")

                run = diff_p.add_run(stext)
                run.font.size = Pt(9.5)
                if stype_val == DiffType.DELETE.value:
                    run.font.strike = True
                    run.font.color.rgb = RGBColor(192, 0, 0)
                elif stype_val == DiffType.INSERT.value:
                    run.font.underline = True
                    run.font.color.rgb = RGBColor(0, 128, 0)
        else:
            p_none = doc.add_paragraph("No redline suggested (Clause complies with standard position).")
            p_none.runs[0].font.italic = True
            p_none.runs[0].font.size = Pt(9.5)

        # Reviewer Decision
        doc.add_heading("Legal Reviewer Decision (Official)", level=3)
        dec_p = doc.add_paragraph()
        if item.decision:
            d = item.decision
            stat = d.status.value.upper() if hasattr(d.status, "value") else str(d.status).upper()
            dec_p.add_run(f"Decision: {stat} by {d.reviewer_name} at {d.decided_at}\n")
            if d.reviewer_note:
                dec_p.add_run(f"Reviewer Note: {d.reviewer_note}\n")
            if d.final_text:
                dec_p.add_run(f"Edited Text: {d.final_text}\n")
        else:
            dec_p.add_run("Decision: No decision required (Acceptable risk).")
        dec_p.runs[0].font.size = Pt(9.5)

        # Resulting Clause Text
        doc.add_heading(f"Resulting Clause Text ({item.resulting_text_source})", level=3)
        res_p = doc.add_paragraph(item.resulting_text)
        res_p.runs[0].font.size = Pt(9.5)
        res_p.runs[0].font.bold = True

        doc.add_paragraph()

    # Appendix
    doc.add_heading("4. Appendix: Decision Audit Trail", level=1)
    aud_table = doc.add_table(rows=1, cols=5)
    aud_table.style = "Table Grid"
    aud_headers = ["Clause ID", "Reviewer", "Decision", "Timestamp", "Note"]
    for i, h in enumerate(aud_headers):
        aud_table.cell(0, i).paragraphs[0].add_run(h).font.bold = True

    for cid, history in report.appendix_decision_history.items():
        for rec in history:
            row = aud_table.add_row()
            row.cells[0].paragraphs[0].add_run(cid)
            row.cells[1].paragraphs[0].add_run(rec.reviewer_name)
            stat = rec.status.value if hasattr(rec.status, "value") else str(rec.status)
            row.cells[2].paragraphs[0].add_run(stat)
            row.cells[3].paragraphs[0].add_run(rec.decided_at[:19])
            row.cells[4].paragraphs[0].add_run(rec.reviewer_note or "—")

    doc.add_paragraph()
    bot_p = doc.add_paragraph()
    bot_run = bot_p.add_run(f"ADVISORY ONLY NOTICE:\n{report.disclaimer}")
    bot_run.font.italic = True
    bot_run.font.size = Pt(9.0)

    # Save to BytesIO
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------
# 3. JSON Export
# ------------------------------------------------------------------------------


def report_to_json(report: ReviewReport) -> str:
    """Serialize ReviewReport model to formatted JSON string."""
    return report.model_dump_json(indent=2)
