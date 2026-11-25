"""Integration tests for contract review lifecycle, persistence, and human approval flow.

Tests:
- Upload validation (bad extension, empty file, file exceeding max size limit)
- Review state transitions: processing -> awaiting_review -> finalized
- Decision validation rules (required reviewer_name, required final_text for edited, required note for rejected)
- Append-only decision audit history
- Finalize gating (blocked 409 with pending clause list until all required clauses are decided)
- Successful finalization and locking (409 on subsequent decision attempts)
- LangGraph SQLite checkpointer interrupt and resume verification
- Offline execution with isolated temporary directories and mocked LLM calls
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.graph.contract_graph import (
    create_contract_analysis_graph,
    process_contract_review_pipeline,
    resume_contract_review_graph,
)
from app.main import app
from app.models.schemas import (
    AnalysisOutput,
    ClassificationOutput,
    Clause,
    ClauseAnalysis,
    CombinedAnalysisOutput,
    DecisionStatus,
    PlaybookRule,
    RiskLevel,
)
from app.services.db import (
    create_review,
    get_clause_analyses,
    get_decisions_for_clause,
    get_latest_decision,
    get_pending_decisions,
    get_review,
    init_db,
    save_clause_analyses,
    update_review_status,
)
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command


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
    }

    async def fake_retrieve(clause_text, clause_type=None, top_k=3, **kwargs):
        return [(rules_map["limitation_of_liability"], 0.95)]

    with patch("app.graph.clause_graph.retrieve_rules", side_effect=fake_retrieve):
        yield rules_map


@pytest.fixture
def isolated_env():
    """Configure temporary isolated database, upload, and checkpoint paths."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = str(tmp_path / "test_app.db")
        chk_path = str(tmp_path / "test_checkpoints.db")
        uploads_dir = str(tmp_path / "uploads")

        init_db(db_path)

        with (
            patch.object(settings, "DB_PATH", db_path),
            patch.object(settings, "CHECKPOINT_DB_PATH", chk_path),
            patch.object(settings, "UPLOADS_DIR", uploads_dir),
            patch.object(settings, "ENABLE_CHECKPOINTER", True),
        ):
            client = TestClient(app)
            yield {
                "client": client,
                "db_path": db_path,
                "chk_path": chk_path,
                "uploads_dir": uploads_dir,
            }


# ------------------------------------------------------------------------------
# 1. Upload Validation Tests
# ------------------------------------------------------------------------------


def test_upload_validation_bad_extension(isolated_env) -> None:
    """Ensure upload rejects files that are not .docx or .pdf."""
    client = isolated_env["client"]
    files = {"file": ("unsupported.txt", b"plain text contract", "text/plain")}
    response = client.post("/contracts/upload", files=files)
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_upload_validation_empty_file(isolated_env) -> None:
    """Ensure upload rejects empty 0-byte files."""
    client = isolated_env["client"]
    files = {"file": ("empty.docx", b"", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    response = client.post("/contracts/upload", files=files)
    assert response.status_code == 400
    assert "Uploaded file is empty" in response.json()["detail"]


def test_upload_validation_too_large(isolated_env) -> None:
    """Ensure upload rejects files exceeding MAX_UPLOAD_SIZE_BYTES."""
    client = isolated_env["client"]
    # Patch MAX_UPLOAD_SIZE_BYTES to 100 bytes for test
    with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", 100):
        files = {
            "file": (
                "large.docx",
                b"x" * 200,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        response = client.post("/contracts/upload", files=files)
        assert response.status_code == 400
        assert "exceeds maximum allowed limit" in response.json()["detail"]


# ------------------------------------------------------------------------------
# 2. Upload, Processing, and Review Detail Tests
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upload_and_processing_flow(isolated_env, mock_retrieval_service) -> None:
    """Test contract upload, background pipeline execution, and review detail retrieval."""
    client = isolated_env["client"]
    sample_doc_path = Path("backend/data/samples/sample_contract_compliant.docx")
    assert sample_doc_path.exists(), "Sample contract docx must exist for test"

    with open(sample_doc_path, "rb") as f:
        file_bytes = f.read()

    # Mock LLM dispatch so pipeline executes fast and deterministically
    async def mock_llm(prompt, system_instruction, response_schema, **kwargs):
        if response_schema == CombinedAnalysisOutput:
            return {
                "clause_type": "limitation_of_liability",
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Standard position satisfied.",
                "confidence": 0.92,
            }
        elif response_schema == ClassificationOutput:
            return {"clause_type": "limitation_of_liability", "confidence": 0.95}
        elif response_schema == AnalysisOutput:
            return {
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Standard position satisfied.",
                "confidence": 0.92,
            }
        return {"suggested_redline": None}

    # Intercept background task to run synchronously in test
    with patch("app.graph.clause_graph.generate_structured_json", side_effect=mock_llm):
        files = {
            "file": (
                "sample_compliant.docx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        response = client.post("/contracts/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        review_id = data["review_id"]
        assert data["status"] == "processing"
        assert "ADVISORY ONLY" in data["disclaimer"]

        # Run the pipeline explicitly to simulate background completion
        stored_path = get_review(review_id)["stored_file_path"]
        await process_contract_review_pipeline(review_id, stored_path)

        # Verify status polling endpoint
        status_res = client.get(f"/reviews/{review_id}/status")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["status"] == "awaiting_review"
        assert status_data["progress"]["analyzed"] == 10
        assert status_data["progress"]["total"] == 10

        # Verify full review detail endpoint
        detail_res = client.get(f"/reviews/{review_id}")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["review_id"] == review_id
        assert detail_data["status"] == "awaiting_review"
        assert len(detail_data["clauses"]) == 10
        assert detail_data["acceptable_count"] == 10
        assert detail_data["pending_decisions"] == 0  # Acceptable clauses without flags need no decision
        assert "ADVISORY ONLY" in detail_data["disclaimer"]


# ------------------------------------------------------------------------------
# 3. Decision Validation Rules & Audit History
# ------------------------------------------------------------------------------


def test_decision_validation_rules(isolated_env) -> None:
    """Ensure strict validation of reviewer name, edited final text, and rejection note."""
    client = isolated_env["client"]
    rev_id = "rev-test-decisions"
    create_review(rev_id, "contract.docx", "/fake/path")
    update_review_status(rev_id, status="awaiting_review")

    # Seed 1 clause with Needs Negotiation
    clause = Clause(id="C-001", section_number="1.0", title="Liability", text="Liability clause text.")
    analysis = ClauseAnalysis(
        clause_id="C-001",
        clause_type="limitation_of_liability",
        risk_level=RiskLevel.NEEDS_NEGOTIATION,
        cited_rule_ids=["LOL-01"],
        explanation="Cap is 6 months instead of 12.",
        suggested_redline="Revised liability cap to 12 months.",
        confidence=0.9,
    )
    save_clause_analyses(rev_id, [clause], [analysis])

    # Rule A: Reviewer name is required and cannot be empty
    res1 = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "approved", "reviewer_name": "   "},
    )
    assert res1.status_code == 422

    # Rule B: Edited decision requires non-empty final_text
    res2 = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "edited", "reviewer_name": "Counsel Alice", "final_text": ""},
    )
    assert res2.status_code == 422

    # Rule C: Rejected decision requires non-empty reviewer_note
    res3 = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "rejected", "reviewer_name": "Counsel Alice", "reviewer_note": ""},
    )
    assert res3.status_code == 422

    # Valid approved decision
    res4 = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "approved", "reviewer_name": "Counsel Alice", "reviewer_note": "Acceptable risk."},
    )
    assert res4.status_code == 200
    assert res4.json()["status"] == "approved"
    assert res4.json()["reviewer_name"] == "Counsel Alice"


def test_decision_audit_history_and_changing_decisions(isolated_env) -> None:
    """Ensure changing a decision appends to the audit log while keeping latest as current."""
    client = isolated_env["client"]
    rev_id = "rev-audit-test"
    create_review(rev_id, "contract.docx", "/fake/path")
    update_review_status(rev_id, status="awaiting_review")

    clause = Clause(id="C-001", section_number="1.0", title="Liability", text="Liability clause text.")
    analysis = ClauseAnalysis(
        clause_id="C-001",
        clause_type="limitation_of_liability",
        risk_level=RiskLevel.NEEDS_NEGOTIATION,
        cited_rule_ids=["LOL-01"],
        explanation="Cap is low.",
        suggested_redline="Redline.",
        confidence=0.88,
    )
    save_clause_analyses(rev_id, [clause], [analysis])

    # 1. First decision: approved
    client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "approved", "reviewer_name": "Alice"},
    )

    # 2. Second decision: changed to edited
    client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={
            "status": "edited",
            "reviewer_name": "Bob",
            "final_text": "Updated liability cap of 2x fees.",
            "reviewer_note": "Increasing to 2x fees.",
        },
    )

    # 3. Third decision: changed to rejected
    client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={
            "status": "rejected",
            "reviewer_name": "Carol",
            "reviewer_note": "Counterparty rejected 2x.",
        },
    )

    # Inspect clause detail endpoint
    res = client.get(f"/reviews/{rev_id}/clauses/C-001")
    assert res.status_code == 200
    data = res.json()

    # Current decision must be Carol's rejected decision
    assert data["current_decision"]["status"] == "rejected"
    assert data["current_decision"]["reviewer_name"] == "Carol"

    # History must have all 3 entries in chronological order
    assert len(data["decision_history"]) == 3
    assert data["decision_history"][0]["reviewer_name"] == "Alice"
    assert data["decision_history"][0]["status"] == "approved"
    assert data["decision_history"][1]["reviewer_name"] == "Bob"
    assert data["decision_history"][1]["status"] == "edited"
    assert data["decision_history"][2]["reviewer_name"] == "Carol"
    assert data["decision_history"][2]["status"] == "rejected"

    # Check that cited_rules contains full PlaybookRule objects
    assert len(data["cited_rules"]) == 1
    assert data["cited_rules"][0]["rule_id"] == "LOL-01"
    assert "Aggregate Liability Cap" in data["cited_rules"][0]["title"]


# ------------------------------------------------------------------------------
# 4. Finalize Gating & Locking Tests
# ------------------------------------------------------------------------------


def test_finalize_blocked_while_decisions_pending(isolated_env) -> None:
    """Ensure finalize returns 409 listing pending clause IDs if required decisions are missing."""
    client = isolated_env["client"]
    rev_id = "rev-pending-gate"
    create_review(rev_id, "contract.docx", "/fake/path")
    update_review_status(rev_id, status="awaiting_review")

    # Add 2 clauses: 1 Needs Negotiation (requires decision), 1 Acceptable (no decision required)
    c1 = Clause(id="C-001", section_number="1.0", title="Indemnity", text="One-sided indemnity.")
    a1 = ClauseAnalysis(
        clause_id="C-001",
        clause_type="indemnification",
        risk_level=RiskLevel.UNACCEPTABLE,
        cited_rule_ids=["IND-01"],
        explanation="One-sided.",
        confidence=0.9,
    )
    c2 = Clause(id="C-002", section_number="2.0", title="Confidentiality", text="Standard mutual.")
    a2 = ClauseAnalysis(
        clause_id="C-002",
        clause_type="confidentiality",
        risk_level=RiskLevel.ACCEPTABLE,
        cited_rule_ids=["CONF-01"],
        explanation="Compliant.",
        confidence=0.95,
        needs_human_review=False,
    )
    save_clause_analyses(rev_id, [c1, c2], [a1, a2])

    # Attempt to finalize before deciding C-001
    res = client.post(f"/reviews/{rev_id}/finalize")
    assert res.status_code == 409
    error_detail = res.json()["detail"]
    assert "pending_clause_ids" in error_detail
    assert "C-001" in error_detail["pending_clause_ids"]
    assert error_detail["pending_count"] == 1


@pytest.mark.anyio
async def test_successful_finalize_and_decision_locking(isolated_env) -> None:
    """Ensure successful finalize locks the review and rejects any subsequent decision modifications."""
    client = isolated_env["client"]
    rev_id = "rev-finalize-lock"
    create_review(rev_id, "contract.docx", "/fake/path")
    update_review_status(rev_id, status="awaiting_review")

    c1 = Clause(id="C-001", section_number="1.0", title="Indemnity", text="One-sided indemnity.")
    a1 = ClauseAnalysis(
        clause_id="C-001",
        clause_type="indemnification",
        risk_level=RiskLevel.UNACCEPTABLE,
        cited_rule_ids=["IND-01"],
        explanation="One-sided.",
        confidence=0.9,
    )
    save_clause_analyses(rev_id, [c1], [a1])

    # Record decision for C-001
    dec_res = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "approved", "reviewer_name": "Counsel Dan", "reviewer_note": "Approved exception."},
    )
    assert dec_res.status_code == 200

    # Finalize should succeed
    fin_res = client.post(f"/reviews/{rev_id}/finalize")
    assert fin_res.status_code == 200
    fin_data = fin_res.json()
    assert fin_data["status"] == "finalized"
    assert fin_data["review_id"] == rev_id
    assert "finalized_at" in fin_data

    # Attempting to add or change a decision after finalization must return 409 Conflict
    post_fin_dec = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "rejected", "reviewer_name": "Counsel Dan", "reviewer_note": "Too late."},
    )
    assert post_fin_dec.status_code == 409
    assert "already finalized" in post_fin_dec.json()["detail"]

    # Attempting to finalize an already finalized review must return 409
    double_fin = client.post(f"/reviews/{rev_id}/finalize")
    assert double_fin.status_code == 409
    assert "already finalized" in double_fin.json()["detail"]


def test_decision_on_processing_review_conflict(isolated_env) -> None:
    """Ensure submitting a decision while review is still processing returns 409."""
    client = isolated_env["client"]
    rev_id = "rev-processing-test"
    create_review(rev_id, "contract.docx", "/fake/path")
    # Review remains in default 'processing' status

    res = client.post(
        f"/reviews/{rev_id}/clauses/C-001/decision",
        json={"status": "approved", "reviewer_name": "Counsel"},
    )
    assert res.status_code == 409
    assert "still processing" in res.json()["detail"]


# ------------------------------------------------------------------------------
# 5. LangGraph Checkpointer Interrupt / Resume Verification
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_langgraph_sqlite_checkpointer_pause_and_resume(isolated_env, mock_retrieval_service) -> None:
    """Explicitly verify that the contract graph interrupts at await_review and resumes cleanly."""
    chk_path = isolated_env["chk_path"]
    thread_id = "thread-checkpoint-test"
    sample_doc_path = str(Path("backend/data/samples/sample_contract_compliant.docx").resolve())

    async def mock_llm_dispatch(prompt, system_instruction, response_schema, **kwargs):
        if response_schema == CombinedAnalysisOutput:
            return {
                "clause_type": "limitation_of_liability",
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Compliant.",
                "confidence": 0.95,
            }
        elif response_schema == ClassificationOutput:
            return {"clause_type": "limitation_of_liability", "confidence": 0.95}
        elif response_schema == AnalysisOutput:
            return {
                "risk_level": "Acceptable",
                "cited_rule_ids": ["LOL-01"],
                "explanation": "Compliant.",
                "confidence": 0.95,
            }
        return {"suggested_redline": None}

    with patch("app.graph.clause_graph.generate_structured_json", side_effect=mock_llm_dispatch):
        config = {"configurable": {"thread_id": thread_id}}

        # Phase 1: Run graph up to the interrupt
        async with AsyncSqliteSaver.from_conn_string(chk_path) as checkpointer:
            graph = create_contract_analysis_graph(checkpointer=checkpointer)
            paused_state = await graph.ainvoke({"file_path": sample_doc_path}, config=config)

            # Assert interrupt occurred
            assert "__interrupt__" in paused_state
            interrupt_info = paused_state["__interrupt__"][0]
            assert interrupt_info.value["review_id"] == thread_id
            assert "Awaiting human legal review" in interrupt_info.value["message"]

            # Summarize node ran before interrupt, so clauses and analyses are present!
            assert len(paused_state["clauses"]) == 10
            assert len(paused_state["analyses"]) == 10
            assert paused_state["total_clauses"] == 10

        # Phase 2: Resume graph with checkpointer
        async with AsyncSqliteSaver.from_conn_string(chk_path) as checkpointer2:
            graph2 = create_contract_analysis_graph(checkpointer=checkpointer2)
            resumed_state = await graph2.ainvoke(
                Command(resume={"finalized_by": "Legal Director"}),
                config=config,
            )

            # Assert finalized node ran and graph completed
            assert resumed_state["review_status"] == "finalized"


def test_path_traversal_filename_sanitization(isolated_env) -> None:
    """Ensure path traversal characters and invalid filenames are stripped safely."""
    client = TestClient(app)
    # Malicious filename containing directory traversal
    file_payload = ("../../../../etc/malicious.docx", b"PK\x03\x04valid-fake-docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    with patch("app.api.reviews.process_contract_review_pipeline", new_callable=AsyncMock):
        response = client.post("/contracts/upload", files={"file": file_payload})

    assert response.status_code == 200
    data = response.json()
    assert ".." not in data["contract_name"]
    assert "/" not in data["contract_name"]
    assert "\\" not in data["contract_name"]
    assert data["contract_name"].endswith(".docx")

    # Filename with only special characters
    special_payload = ("???!!!***.docx", b"PK\x03\x04valid-fake-docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    with patch("app.api.reviews.process_contract_review_pipeline", new_callable=AsyncMock):
        resp2 = client.post("/contracts/upload", files={"file": special_payload})
    assert resp2.status_code == 200
    assert resp2.json()["contract_name"] == "uploaded_contract.docx"


def test_cors_headers_allowed_origin() -> None:
    """Ensure CORS allows frontend origins like http://localhost:5173."""
    client = TestClient(app)
    response = client.options(
        "/contracts/upload",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_finalize_after_simulated_restart(isolated_env) -> None:
    """Ensure finalize still succeeds and locks review even after a server restart."""
    db_path = isolated_env["db_path"]
    client = TestClient(app)
    review_id = "restart-test-review"

    # Create review directly in awaiting_review status
    create_review(
        review_id=review_id,
        contract_name="test_restart.docx",
        stored_file_path="/tmp/test_restart.docx",
        db_path=db_path,
    )
    clauses = [
        Clause(id="C-001", section_number="1", title="Termination", text="Either party may terminate on 30 days notice.")
    ]
    analyses = [
        ClauseAnalysis(
            clause_id="C-001",
            clause_type="termination",
            risk_level=RiskLevel.ACCEPTABLE,
            cited_rule_ids=["TRM-01"],
            explanation="Standard position.",
            confidence=0.95,
        )
    ]
    save_clause_analyses(review_id, clauses, analyses, [], db_path=db_path)
    update_review_status(review_id, "awaiting_review", total_clauses=1, analyzed_clauses=1, db_path=db_path)

    # Simulate restart by clearing any in-memory references, then call finalize
    resp = client.post(f"/reviews/{review_id}/finalize")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "finalized"
    assert "finalized successfully" in data["message"].lower()

    # Verify review in DB is locked
    review_in_db = get_review(review_id, db_path=db_path)
    assert review_in_db["status"] == "finalized"
    assert review_in_db["finalized_at"] is not None

