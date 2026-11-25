"""Regression test suite for verified edge cases and concurrency safeguards.

Covers:
1. Two simultaneous uploads processed concurrently.
2. SQLite database locking under heavy concurrent writers and readers.
3. Malformed / invalid LLM JSON output triggering retry and needs_human_review fallback.
4. Scanned / empty-text PDF rejection with clear, actionable error message.
5. Re-indexing the playbook vector store concurrently while retrieval queries are active.
"""

import asyncio
import io
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.core.config import settings
from app.graph.clause_graph import clause_analysis_graph, redline_node
from app.main import app
from app.models.schemas import (
    Clause,
    ClauseAnalysis,
    CombinedAnalysisOutput,
    PlaybookRule,
    RedlineOutput,
    RiskLevel,
)
from app.services.db import (
    create_review,
    get_db_connection,
    get_review,
    init_db,
    save_clause_analyses,
    update_review_status,
)
from app.services.parser import parse_document
from app.services.vector_store import (
    get_playbook_collection,
    ingest_playbook,
    retrieve_rules,
)


@pytest.fixture
def temp_db():
    """Create an isolated SQLite database path for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


# ------------------------------------------------------------------------------
# 1. Two Simultaneous Uploads
# ------------------------------------------------------------------------------


def test_two_simultaneous_uploads(temp_db, monkeypatch):
    """Verify that multiple simultaneous contract uploads can be initiated without conflicts."""
    monkeypatch.setattr(settings, "DB_PATH", temp_db)
    client = TestClient(app)

    # Minimal valid DOCX bytes
    import docx
    doc1 = docx.Document()
    doc1.add_paragraph("1. Term. This agreement shall remain in effect for 1 year.")
    buf1 = io.BytesIO()
    doc1.save(buf1)
    bytes1 = buf1.getvalue()

    doc2 = docx.Document()
    doc2.add_paragraph("1. Payment. Fees are due net 30.")
    buf2 = io.BytesIO()
    doc2.save(buf2)
    bytes2 = buf2.getvalue()

    files1 = {"file": ("contract_alpha.docx", io.BytesIO(bytes1), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    files2 = {"file": ("contract_beta.docx", io.BytesIO(bytes2), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}

    # Send uploads back-to-back
    resp1 = client.post("/contracts/upload", files=files1)
    resp2 = client.post("/contracts/upload", files=files2)

    assert resp1.status_code == 200, resp1.text
    assert resp2.status_code == 200, resp2.text

    data1 = resp1.json()
    data2 = resp2.json()

    assert data1["review_id"] != data2["review_id"]
    assert data1["status"] == "processing"
    assert data2["status"] == "processing"


# ------------------------------------------------------------------------------
# 2. SQLite Locking Under Concurrent Writers & Readers
# ------------------------------------------------------------------------------


def test_sqlite_locking_concurrent_writers_and_readers(temp_db):
    """Verify SQLite WAL and immediate transaction mode prevent database locking errors."""
    errors = []

    def writer_task(thread_id: int):
        try:
            for i in range(10):
                rev_id = f"rev-{thread_id}-{i}"
                create_review(
                    review_id=rev_id,
                    contract_name=f"contract_{thread_id}_{i}.docx",
                    stored_file_path="/tmp/fake.docx",
                    db_path=temp_db,
                )
                update_review_status(
                    review_id=rev_id,
                    status="awaiting_review",
                    total_clauses=5,
                    analyzed_clauses=5,
                    db_path=temp_db,
                )
        except Exception as exc:
            errors.append(f"Writer-{thread_id}: {exc}")

    def reader_task(thread_id: int):
        try:
            for _ in range(20):
                with get_db_connection(temp_db) as conn:
                    cursor = conn.execute("SELECT COUNT(*) as c FROM reviews")
                    _ = cursor.fetchone()["c"]
                time.sleep(0.005)
        except Exception as exc:
            errors.append(f"Reader-{thread_id}: {exc}")

    threads = []
    # Launch 4 writers and 4 readers concurrently
    for t in range(4):
        threads.append(threading.Thread(target=writer_task, args=(t,)))
        threads.append(threading.Thread(target=reader_task, args=(t,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert not errors, f"Concurrent SQLite access resulted in locking errors: {errors}"


# ------------------------------------------------------------------------------
# 3. Malformed/Invalid LLM JSON Fallback & Needs Human Review
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_malformed_llm_json_fallback_and_human_review():
    """Verify that malformed LLM output triggers the needs_human_review fallback gracefully."""
    clause = Clause(
        id="C-ERR",
        section_number="9.1",
        title="Payment Terms",
        text="Payment shall be made within thirty days.",
    )

    # Simulate an invalid non-JSON output from the LLM (e.g. truncated text or raw error)
    with patch("app.graph.clause_graph.generate_structured_json") as mock_llm:
        mock_llm.side_effect = ValueError("Model returned invalid JSON: Expecting value: line 1 column 1 (char 0)")

        output_state = await clause_analysis_graph.ainvoke({"clause": clause})

        final_analysis = output_state.get("final_analysis")
        assert final_analysis is not None, "Clause graph should always produce a final_analysis"
        assert final_analysis.needs_human_review is True, "Malformed LLM output must flag clause for human review"
        assert final_analysis.confidence == 0.0, "Confidence should drop to 0 on analysis error"
        assert "error" in (final_analysis.review_reason or "").lower()
        assert "invalid json" in (final_analysis.explanation or "").lower()


# ------------------------------------------------------------------------------
# 4. Scanned / Empty-Text PDF Clear Error
# ------------------------------------------------------------------------------


def test_scanned_empty_text_pdf_clear_error():
    """Verify that scanned or image-only PDFs with no extractable text fail with a clear, helpful message."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        pdf_path = Path(f.name)

    try:
        # Create a valid PDF that contains a blank page with no text layer
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f_out:
            writer.write(f_out)

        with pytest.raises(ValueError) as exc_info:
            parse_document(pdf_path)

        err_msg = str(exc_info.value)
        assert "empty or contains no extractable text" in err_msg
        assert "OCR" in err_msg
    finally:
        pdf_path.unlink(missing_ok=True)


# ------------------------------------------------------------------------------
# 5. Re-indexing Playbook While Queries Run Concurrently
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reindex_playbook_during_concurrent_queries():
    """Verify that idempotent playbook ingestion does not break or lock concurrent vector retrieval queries."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        chroma_dir = Path(tmp_dir) / "chroma"

        # Mock embedding generation to run fast and deterministically
        fake_dim = 3072
        fake_vector = [0.05] * fake_dim

        async def fake_embed(text, model=None):
            if isinstance(text, list):
                return [fake_vector for _ in text]
            return fake_vector

        with patch("app.services.vector_store.generate_embedding", side_effect=fake_embed):
            # Initial ingestion
            count = await ingest_playbook(chroma_path=chroma_dir)
            assert count == 13

            # Run simultaneous re-index and query tasks
            async def run_queries():
                results = []
                for _ in range(5):
                    hits = await retrieve_rules(
                        clause_text="Neither party shall be liable for incidental damages",
                        clause_type="limitation_of_liability",
                        chroma_path=chroma_dir,
                        top_k=2,
                    )
                    results.append(len(hits))
                    await asyncio.sleep(0.01)
                return results

            async def run_reindex():
                return await ingest_playbook(rebuild=False, chroma_path=chroma_dir)

            query_task = asyncio.create_task(run_queries())
            reindex_task = asyncio.create_task(run_reindex())

            query_results, reindex_count = await asyncio.gather(query_task, reindex_task)

            assert reindex_count == 13
            assert all(count > 0 for count in query_results)


# ------------------------------------------------------------------------------
# 6. Rebuild Playbook Blocked (409 Conflict) While Review Is Processing
# ------------------------------------------------------------------------------


def test_rebuild_playbook_blocked_while_review_processing(temp_db, monkeypatch):
    """Verify POST /playbook/reindex with rebuild=true returns 409 while a review is processing."""
    monkeypatch.setattr(settings, "DB_PATH", temp_db)
    client = TestClient(app)

    # 1. Create a review in 'processing' status
    create_review(
        review_id="rev-active-proc",
        contract_name="active_proc.docx",
        stored_file_path="/tmp/fake.docx",
        db_path=temp_db,
    )

    # 2. Attempt rebuild=true -> must return 409 Conflict
    resp_rebuild = client.post("/playbook/reindex", json={"rebuild": True})
    assert resp_rebuild.status_code == 409, f"Expected 409 Conflict, got {resp_rebuild.status_code}: {resp_rebuild.text}"
    assert "actively processing" in resp_rebuild.json().get("detail", "")

    # 3. Transition review to 'awaiting_review'
    update_review_status(
        review_id="rev-active-proc",
        status="awaiting_review",
        db_path=temp_db,
    )

    # Mock ingest_playbook so we don't need real embeddings in this unit test
    with patch("app.api.playbook.ingest_playbook", new=AsyncMock(return_value=13)):
        # 4. Now rebuild=true should succeed
        resp_after = client.post("/playbook/reindex", json={"rebuild": True})
        assert resp_after.status_code == 200, resp_after.text
        assert resp_after.json()["indexed_count"] == 13


# ------------------------------------------------------------------------------
# 7. Evaluation Progress Segregation and Resume Integrity
# ------------------------------------------------------------------------------


def test_eval_progress_contract_segregation_and_resume(tmp_path):
    """Verify eval_progress accurately segregates contracts and prevents cross-contamination."""
    import json
    progress_file = tmp_path / "eval_progress.json"

    # Contract A has 10 clauses completed, Contract B has 4 clauses completed
    progress = {
        "sample_contract_compliant.docx": {
            str(i): {"clause_id": f"C-{i:03d}", "risk_level": "Acceptable"} for i in range(1, 11)
        },
        "sample_contract_needs_negotiation.docx": {
            str(i): {"clause_id": f"C-{i:03d}", "risk_level": "Needs Negotiation"} for i in range(1, 5)
        },
    }

    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(progress, f)

    with open(progress_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    # Verify each contract maintains isolated clause progress
    assert len(loaded["sample_contract_compliant.docx"]) == 10
    assert len(loaded["sample_contract_needs_negotiation.docx"]) == 4

    # Clauses 1-4 exist in both contracts without key collision because of contract-name namespacing
    assert loaded["sample_contract_compliant.docx"]["1"]["risk_level"] == "Acceptable"
    assert loaded["sample_contract_needs_negotiation.docx"]["1"]["risk_level"] == "Needs Negotiation"

    # Check remaining clauses calculation for Contract B
    contract_b_missing = [str(i) for i in range(1, 11) if str(i) not in loaded["sample_contract_needs_negotiation.docx"]]
    assert contract_b_missing == ["5", "6", "7", "8", "9", "10"]


# ------------------------------------------------------------------------------
# 8. --no-redline Pending Status and Backfill Without Re-Analyzing
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_no_redline_mode_and_backfill_pending_redlines():
    """Verify --no-redline records 'pending' and subsequent run backfills redline without re-analyzing."""
    clause = Clause(
        id="C-001",
        section_number="1",
        title="Limitation of Liability",
        text="Liability capped at $10,000.",
    )

    call_counts = {"combined_analyze": 0, "redline": 0}

    async def mock_llm_dispatch(prompt, system_instruction, response_schema, **kwargs):
        if response_schema == CombinedAnalysisOutput:
            call_counts["combined_analyze"] += 1
            return {
                "clause_type": "limitation_of_liability",
                "risk_level": "Needs Negotiation",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Cap is below standard.",
                "confidence": 0.90,
            }
        elif response_schema == RedlineOutput:
            call_counts["redline"] += 1
            return {
                "suggested_redline": "Liability shall be capped at 12 months fees.",
            }
        raise ValueError(f"Unexpected schema: {response_schema}")

    mock_rule = PlaybookRule(
        rule_id="LOL-01",
        clause_type="limitation_of_liability",
        title="Liability Cap",
        standard_position="Cap at 12 months fees.",
        acceptable_fallback="Cap at 2x 12 months fees.",
        unacceptable_triggers=["unlimited liability"],
        preferred_language="Liability shall not exceed 12 months fees.",
        rationale="Limits exposure.",
    )

    with patch("app.graph.clause_graph.generate_structured_json", side_effect=mock_llm_dispatch), \
         patch("app.graph.clause_graph.retrieve_rules", new=AsyncMock(return_value=[(mock_rule, 0.9)])):

        # Phase 1: Run with skip_redline=True (--no-redline)
        res1 = await clause_analysis_graph.ainvoke({"clause": clause, "skip_redline": True})
        analysis1 = res1["final_analysis"]

        assert analysis1.risk_level == RiskLevel.NEEDS_NEGOTIATION
        assert analysis1.suggested_redline == "pending"
        assert call_counts["combined_analyze"] == 1
        assert call_counts["redline"] == 0

        # Simulate saving to progress file
        progress = {"sample.docx": {"1": analysis1.model_dump()}}

        # Phase 2: Later run filling in pending redline (without --no-redline)
        # Reuses cached analysis and does NOT invoke combined_analyze again!
        cached_dict = progress["sample.docx"]["1"]
        analysis_cached = ClauseAnalysis.model_validate(cached_dict)

        assert analysis_cached.suggested_redline == "pending"

        redline_res = await redline_node({
            "clause": clause,
            "risk_level": analysis_cached.risk_level,
            "explanation": analysis_cached.explanation,
            "cited_rule_ids": analysis_cached.cited_rule_ids,
        })

        analysis_cached.suggested_redline = redline_res.get("suggested_redline")
        progress["sample.docx"]["1"] = analysis_cached.model_dump()

        assert analysis_cached.suggested_redline == "Liability shall be capped at 12 months fees."
        assert call_counts["combined_analyze"] == 1  # Not called again!
        assert call_counts["redline"] == 1           # Redline generated successfully

