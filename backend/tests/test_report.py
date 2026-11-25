"""Tests for the word-level diff service, deterministic report builder, and export formats.

Covers:
- Diff helper round-trip property, insert-only, delete-only, replace, identical, and empty strings.
- Report builder summary counts, resulting clause text rules, disclaimers, audit trail, missing clauses.
- Markdown, DOCX (verifying document structure via python-docx), and JSON export formats.
- API endpoints: 404 for unknown review, 409 for non-finalized review, and 200 for all 3 formats on finalized reviews.
"""

from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import docx
from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.main import app
from app.models.schemas import (
    Clause,
    ClauseAnalysis,
    DecisionStatus,
    DiffSegment,
    DiffType,
    ReviewDecisionRecord,
    ReviewReport,
    RiskLevel,
)
from app.services.db import (
    add_decision,
    create_review,
    init_db,
    save_clause_analyses,
    update_review_status,
)
from app.services.diff import (
    compute_word_diff,
    reconstruct_original,
    reconstruct_revised,
)
from app.services.report import build_review_report
from app.services.report_export import (
    report_to_docx,
    report_to_json,
    report_to_markdown,
)


# ------------------------------------------------------------------------------
# 1. Diff Helper Tests
# ------------------------------------------------------------------------------


def test_diff_helper_identical_text() -> None:
    """Ensure identical texts return a single equal segment preserving text."""
    orig = "This Agreement is governed by Delaware law."
    revised = "This Agreement is governed by Delaware law."
    segments = compute_word_diff(orig, revised)
    assert len(segments) == 1
    assert segments[0]["type"] == DiffType.EQUAL.value
    assert segments[0]["text"] == orig
    assert reconstruct_original(segments) == orig
    assert reconstruct_revised(segments) == revised


def test_diff_helper_empty_strings() -> None:
    """Ensure empty strings are handled without errors and round-trip."""
    assert compute_word_diff("", "") == []

    # Insert from empty
    ins_segments = compute_word_diff("", "New clause text.")
    assert reconstruct_original(ins_segments) == ""
    assert reconstruct_revised(ins_segments) == "New clause text."

    # Delete to empty
    del_segments = compute_word_diff("Old clause text.", "")
    assert reconstruct_original(del_segments) == "Old clause text."
    assert reconstruct_revised(del_segments) == ""


def test_diff_helper_insert_only() -> None:
    """Ensure insertion of words preserves original and produces revised text."""
    orig = "Liability is capped."
    revised = "Liability is capped at 12 months fees."
    segments = compute_word_diff(orig, revised)

    assert reconstruct_original(segments) == orig
    assert reconstruct_revised(segments) == revised
    assert any(s["type"] == DiffType.INSERT.value and "12 months" in s["text"] for s in segments)


def test_diff_helper_delete_only() -> None:
    """Ensure deletion of words removes them from revised while retaining in original."""
    orig = "Customer shall provide thirty (30) days notice."
    revised = "Customer shall provide notice."
    segments = compute_word_diff(orig, revised)

    assert reconstruct_original(segments) == orig
    assert reconstruct_revised(segments) == revised
    assert any(s["type"] == DiffType.DELETE.value and "thirty (30) days" in s["text"] for s in segments)


def test_diff_helper_replacement_and_round_trip() -> None:
    """Ensure complex replacements maintain the exact round-trip property with whitespace."""
    orig = "In no event shall liability exceed $100,000 for any and all claims."
    revised = "In no event shall liability exceed 12 months of fees paid for all claims."
    segments = compute_word_diff(orig, revised)

    # Fundamental round-trip invariants:
    orig_reconstructed = reconstruct_original(segments)
    revised_reconstructed = reconstruct_revised(segments)

    assert orig_reconstructed == orig
    assert revised_reconstructed == revised


# ------------------------------------------------------------------------------
# 2. Report Builder & Resulting Text Rules
# ------------------------------------------------------------------------------


@pytest.fixture
def sample_finalized_review():
    """Create a temporary database with a finalized review containing approved, edited, and rejected clauses."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test_report.db")
        init_db(db_path)

        review_id = "rev-rep-test-01"
        contract_name = "test_vendor_agreement.docx"
        create_review(review_id, contract_name, "/tmp/test.docx", db_path=db_path)

        clauses = [
            Clause(id="C-001", section_number="1.0", title="Liability", text="Liability is capped at 6 months."),
            Clause(id="C-002", section_number="2.0", title="Indemnity", text="Customer indemnifies Company only."),
            Clause(id="C-003", section_number="3.0", title="Termination", text="Termination on 90 days notice."),
            Clause(id="C-004", section_number="4.0", title="Confidentiality", text="Mutual 5-year confidentiality."),
        ]

        analyses = [
            ClauseAnalysis(
                clause_id="C-001",
                clause_type="limitation_of_liability",
                risk_level=RiskLevel.NEEDS_NEGOTIATION,
                cited_rule_ids=["LOL-01"],
                explanation="Cap is 6 months instead of 12.",
                suggested_redline="Liability is capped at 12 months.",
                confidence=0.90,
            ),
            ClauseAnalysis(
                clause_id="C-002",
                clause_type="indemnification",
                risk_level=RiskLevel.UNACCEPTABLE,
                cited_rule_ids=["IND-01"],
                explanation="One-sided indemnity.",
                suggested_redline="Mutual indemnification for IP and data.",
                confidence=0.95,
                needs_human_review=True,
                review_reason="One-sided trigger",
            ),
            ClauseAnalysis(
                clause_id="C-003",
                clause_type="termination",
                risk_level=RiskLevel.NEEDS_NEGOTIATION,
                cited_rule_ids=["TRM-01"],
                explanation="90 days notice is lengthy.",
                suggested_redline="Termination on 30 days notice.",
                confidence=0.88,
            ),
            ClauseAnalysis(
                clause_id="C-004",
                clause_type="confidentiality",
                risk_level=RiskLevel.ACCEPTABLE,
                cited_rule_ids=["CONF-01"],
                explanation="Standard position met.",
                confidence=0.99,
            ),
        ]

        missing_types = ["governing_law", "ip_ownership", "payment_terms"]
        save_clause_analyses(review_id, clauses, analyses, missing_clauses=missing_types, db_path=db_path)
        update_review_status(review_id, status="awaiting_review", db_path=db_path)

        # 1. Superseded decision on C-001, then EDITED
        add_decision(
            review_id, "C-001", "rejected", "Associate Dave", "Initial reject.",
            db_path=db_path,
        )
        add_decision(
            review_id, "C-001", "edited", "Counsel Alice", "Compromise cap.",
            final_text="Liability is capped at 12 months fees or $500k.",
            db_path=db_path,
        )

        # 2. APPROVED decision on C-002
        add_decision(
            review_id, "C-002", "approved", "Counsel Alice", "Accepted mutual redline.",
            db_path=db_path,
        )

        # 3. REJECTED decision on C-003 (keeps original text)
        add_decision(
            review_id, "C-003", "rejected", "Counsel Alice", "Counterparty insisted on 90 days.",
            db_path=db_path,
        )

        # Finalize review
        update_review_status(
            review_id,
            status="finalized",
            finalized_at=datetime.utcnow().isoformat(),
            db_path=db_path,
        )

        yield {
            "review_id": review_id,
            "db_path": db_path,
            "contract_name": contract_name,
            "missing_types": missing_types,
        }


def test_report_builder_content_and_resulting_text_rules(sample_finalized_review) -> None:
    """Verify that build_review_report computes correct counts, resulting text, and audit trails."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]

    report = build_review_report(rev_id, db_path=db_path)

    # 1. Basic header & counts
    assert report.review_id == rev_id
    assert report.total_clauses == 4
    assert report.acceptable_count == 1
    assert report.needs_negotiation_count == 2
    assert report.unacceptable_count == 1
    assert report.needs_human_review_count == 1
    assert report.approved_count == 1
    assert report.edited_count == 1
    assert report.rejected_count == 1
    assert "Alice" in report.reviewers[0] or "Dave" in report.reviewers[0]
    assert "ADVISORY ONLY" in report.disclaimer

    # 2. Missing clause types
    assert set(report.missing_clause_types) == {"governing_law", "ip_ownership", "payment_terms"}

    # 3. Resulting clause text rules:
    # C-001 was EDITED: resulting text MUST be final_text
    c1 = next(c for c in report.clauses if c.clause_id == "C-001")
    assert c1.resulting_text == "Liability is capped at 12 months fees or $500k."
    assert "edited by legal reviewer" in c1.resulting_text_source

    # C-002 was APPROVED: resulting text MUST be suggested_redline
    c2 = next(c for c in report.clauses if c.clause_id == "C-002")
    assert c2.resulting_text == "Mutual indemnification for IP and data."
    assert "approved by legal reviewer" in c2.resulting_text_source

    # C-003 was REJECTED: resulting text MUST be original_text
    c3 = next(c for c in report.clauses if c.clause_id == "C-003")
    assert c3.resulting_text == "Termination on 90 days notice."
    assert "rejected by legal reviewer" in c3.resulting_text_source

    # C-004 was ACCEPTABLE (no decision): resulting text MUST be original_text
    c4 = next(c for c in report.clauses if c.clause_id == "C-004")
    assert c4.resulting_text == "Mutual 5-year confidentiality."
    assert "compliant/no changes required" in c4.resulting_text_source

    # 4. Audit trail preserves superseded decision on C-001
    c1_history = report.appendix_decision_history["C-001"]
    assert len(c1_history) == 2
    assert c1_history[0].status == DecisionStatus.REJECTED
    assert c1_history[0].reviewer_name == "Associate Dave"
    assert c1_history[1].status == DecisionStatus.EDITED
    assert c1_history[1].reviewer_name == "Counsel Alice"


# ------------------------------------------------------------------------------
# 3. Export Formats (Markdown, DOCX, JSON)
# ------------------------------------------------------------------------------


def test_export_markdown(sample_finalized_review) -> None:
    """Ensure Markdown export includes all sections, disclaimers, and diff markup."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]
    report = build_review_report(rev_id, db_path=db_path)

    md = report_to_markdown(report)
    assert "# Contract Review and Redline Report" in md
    assert "IMPORTANT LEGAL NOTICE: ADVISORY ONLY" in md
    assert "Risk Assessment Breakdown" in md
    assert "Human Review Decisions" in md
    assert "Contract-Level Findings" in md
    assert "Governing Law" in md
    assert "Resulting Clause Text" in md
    assert "Appendix: Complete Decision Audit Trail" in md
    assert "Associate Dave" in md


def test_export_docx(sample_finalized_review) -> None:
    """Ensure DOCX export generates valid document containing title, tables, and clauses."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]
    report = build_review_report(rev_id, db_path=db_path)

    docx_bytes = report_to_docx(report)
    assert len(docx_bytes) > 1000

    # Parse back with python-docx to verify integrity
    doc = docx.Document(io.BytesIO(docx_bytes))
    all_text = " ".join(p.text for p in doc.paragraphs)
    assert "Contract Review & Redline Report" in all_text
    assert "ADVISORY ONLY" in all_text
    assert "Section 1.0" in all_text
    assert "Section 2.0" in all_text


def test_export_json_roundtrip(sample_finalized_review) -> None:
    """Ensure JSON export serializes and round-trips into ReviewReport model."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]
    report = build_review_report(rev_id, db_path=db_path)

    json_str = report_to_json(report)
    assert isinstance(json_str, str)
    data = json.loads(json_str)

    # Re-instantiate model from parsed JSON
    roundtripped = ReviewReport.model_validate(data)
    assert roundtripped.report_id == report.report_id
    assert roundtripped.total_clauses == report.total_clauses
    assert len(roundtripped.clauses) == len(report.clauses)


# ------------------------------------------------------------------------------
# 4. API Endpoint Tests
# ------------------------------------------------------------------------------


def test_report_endpoint_non_finalized_conflict(sample_finalized_review) -> None:
    """Ensure GET /reviews/{review_id}/report returns 409 if review is not finalized."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]

    # Temporarily revert status to awaiting_review
    update_review_status(rev_id, status="awaiting_review", db_path=db_path)

    with patch.object(settings, "DB_PATH", db_path):
        client = TestClient(app)
        res = client.get(f"/reviews/{rev_id}/report?format=json")
        assert res.status_code == 409
        assert "Report can only be generated for finalized reviews" in res.json()["detail"]


def test_report_endpoint_unknown_id(sample_finalized_review) -> None:
    """Ensure GET /reviews/{review_id}/report returns 404 for unknown review ID."""
    db_path = sample_finalized_review["db_path"]
    with patch.object(settings, "DB_PATH", db_path):
        client = TestClient(app)
        res = client.get("/reviews/nonexistent-uuid-999/report?format=json")
        assert res.status_code == 404


def test_report_endpoint_unsupported_format(sample_finalized_review) -> None:
    """Ensure GET /reviews/{review_id}/report returns 400 for unsupported format."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]
    with patch.object(settings, "DB_PATH", db_path):
        client = TestClient(app)
        res = client.get(f"/reviews/{rev_id}/report?format=pdf")
        assert res.status_code == 400
        assert "Unsupported format 'pdf'" in res.json()["detail"]


def test_report_endpoint_all_formats_success(sample_finalized_review) -> None:
    """Ensure GET /reviews/{review_id}/report succeeds for json, md, and docx on finalized review."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]

    with patch.object(settings, "DB_PATH", db_path):
        client = TestClient(app)

        # 1. JSON
        res_json = client.get(f"/reviews/{rev_id}/report?format=json")
        assert res_json.status_code == 200
        assert res_json.headers["content-type"].startswith("application/json")
        json_body = res_json.json()
        assert json_body["total_clauses"] == 4
        assert "ADVISORY ONLY" in json_body["disclaimer"]

        # 2. Markdown
        res_md = client.get(f"/reviews/{rev_id}/report?format=md")
        assert res_md.status_code == 200
        assert "text/markdown" in res_md.headers["content-type"]
        assert "Contract Review and Redline Report" in res_md.text

        # 3. DOCX
        res_docx = client.get(f"/reviews/{rev_id}/report?format=docx")
        assert res_docx.status_code == 200
        assert "officedocument.wordprocessingml.document" in res_docx.headers["content-type"]
        assert len(res_docx.content) > 1000
        # Check Content-Disposition header
        assert "attachment; filename=" in res_docx.headers["content-disposition"]


def test_clause_detail_endpoint_diff_inclusion(sample_finalized_review) -> None:
    """Ensure GET /reviews/{review_id}/clauses/{clause_id} includes redline_diff and decision_diff."""
    rev_id = sample_finalized_review["review_id"]
    db_path = sample_finalized_review["db_path"]

    with patch.object(settings, "DB_PATH", db_path):
        client = TestClient(app)
        res = client.get(f"/reviews/{rev_id}/clauses/C-001")
        assert res.status_code == 200
        data = res.json()

        # Both redline_diff (original vs AI redline) and decision_diff (original vs reviewer final_text) must be present
        assert data["redline_diff"] is not None
        assert len(data["redline_diff"]) > 0
        assert any(d["type"] == "delete" for d in data["redline_diff"])

        assert data["decision_diff"] is not None
        assert len(data["decision_diff"]) > 0
        assert any(d["type"] == "insert" for d in data["decision_diff"])
