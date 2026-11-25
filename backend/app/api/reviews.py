"""FastAPI route handlers for contract uploads, review lifecycle, and human approval flow.

Enforces:
- File validation (only .docx and .pdf, max size limit, non-empty)
- Human-in-the-loop decision gating (mandatory approval for Needs Negotiation / Unacceptable / flagged clauses)
- Append-only decision audit logging
- Full legal disclaimer on all advisory responses
"""

import asyncio
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status

from app.core.config import settings
from app.graph.contract_graph import (
    process_contract_review_pipeline,
    resume_contract_review_graph,
)
from app.models.schemas import (
    ClauseAnalysis,
    ClauseDetailResponse,
    ClauseWithDecision,
    DecisionRequest,
    DiffSegment,
    FinalizeResponse,
    PlaybookRule,
    ReviewDecisionRecord,
    ReviewDetailResponse,
    ReviewReport,
    ReviewStatus,
    ReviewStatusResponse,
    ReviewSummary,
    UploadResponse,
)
from app.services.db import (
    add_decision,
    create_review,
    get_clause_analyses,
    get_clause_analysis,
    get_decisions_for_clause,
    get_latest_decisions,
    get_pending_decisions,
    get_review,
    get_risk_counts_and_pending,
    list_reviews,
    update_review_status,
)
from app.services.diff import compute_word_diff
from app.services.playbook import get_rule
from app.services.report import build_review_report
from app.services.report_export import (
    report_to_docx,
    report_to_json,
    report_to_markdown,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reviews & Approvals"])

ALLOWED_EXTENSIONS = {".docx", ".pdf"}


# ------------------------------------------------------------------------------
# 1. Upload Contract Endpoint
# ------------------------------------------------------------------------------


@router.post(
    "/contracts/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload contract file for parsing and risk analysis",
)
async def upload_contract(
    file: UploadFile = File(..., description="Target contract document (.docx or .pdf)"),
) -> UploadResponse:
    """Accept and validate a contract file, create review record, and trigger background analysis."""
    # 1. Validate file extension
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{suffix}'. Only .docx and .pdf files are accepted.",
        )

    # 2. Read content in chunks and validate size before buffer accumulation
    chunks = []
    total_bytes = 0
    chunk_size = 65536  # 64 KB
    max_bytes = settings.MAX_UPLOAD_SIZE_BYTES
    max_mb = max_bytes // (1024 * 1024)

    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size exceeds maximum allowed limit of {max_mb} MB.",
            )
        chunks.append(chunk)

    if total_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    content = b"".join(chunks)

    # 3. Sanitize filename against path traversal and store on disk
    raw_name = Path(filename).name
    clean_stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", Path(raw_name).stem).strip("._")
    if not clean_stem:
        clean_stem = "uploaded_contract"
    clean_name = f"{clean_stem}{suffix}"
    review_id = str(uuid.uuid4())

    uploads_dir = Path(settings.UPLOADS_DIR).resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stored_path = str(uploads_dir / f"{review_id}_{clean_name}")

    with open(stored_path, "wb") as f:
        f.write(content)

    # 4. Create review record in 'processing' status
    create_review(
        review_id=review_id,
        contract_name=clean_name,
        stored_file_path=stored_path,
    )

    # 5. Launch analysis workflow in background
    asyncio.create_task(
        process_contract_review_pipeline(
            review_id=review_id,
            file_path=stored_path,
        )
    )

    return UploadResponse(
        review_id=review_id,
        contract_name=clean_name,
        status=ReviewStatus.PROCESSING,
        disclaimer=settings.LEGAL_DISCLAIMER,
    )


# ------------------------------------------------------------------------------
# 2. List Reviews Endpoint
# ------------------------------------------------------------------------------


@router.get(
    "/reviews",
    response_model=List[ReviewSummary],
    summary="List all contract reviews with aggregated risk metrics",
)
async def get_reviews() -> List[ReviewSummary]:
    """Retrieve summaries of all reviews with risk level breakdown and pending decision counts."""
    summaries_data = list_reviews()
    return [
        ReviewSummary(
            review_id=s["review_id"],
            contract_name=s["contract_name"],
            status=ReviewStatus(s["status"]),
            created_at=s["created_at"],
            finalized_at=s.get("finalized_at"),
            total_clauses=s.get("total_clauses", 0),
            analyzed_clauses=s.get("analyzed_clauses", 0),
            acceptable_count=s.get("acceptable_count", 0),
            needs_negotiation_count=s.get("needs_negotiation_count", 0),
            unacceptable_count=s.get("unacceptable_count", 0),
            needs_human_review_count=s.get("needs_human_review_count", 0),
            pending_decisions=s.get("pending_decisions", 0),
            error_message=s.get("error_message"),
            disclaimer=settings.LEGAL_DISCLAIMER,
        )
        for s in summaries_data
    ]


# ------------------------------------------------------------------------------
# 3. Review Status Endpoint (Polling)
# ------------------------------------------------------------------------------


@router.get(
    "/reviews/{review_id}/status",
    response_model=ReviewStatusResponse,
    summary="Poll lightweight status and progress for a review",
)
async def get_review_status(review_id: str) -> ReviewStatusResponse:
    """Return current review status, progress counts, and pending decision totals."""
    review = get_review(review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review '{review_id}' not found.",
        )

    pending_count, _ = get_pending_decisions(review_id)

    return ReviewStatusResponse(
        review_id=review_id,
        status=ReviewStatus(review["status"]),
        progress={
            "analyzed": review.get("analyzed_clauses", 0),
            "total": review.get("total_clauses", 0),
        },
        pending_decisions=pending_count,
        error_message=review.get("error_message"),
        disclaimer=settings.LEGAL_DISCLAIMER,
    )


# ------------------------------------------------------------------------------
# 4. Review Detail Endpoint
# ------------------------------------------------------------------------------


@router.get(
    "/reviews/{review_id}",
    response_model=ReviewDetailResponse,
    summary="Get complete review details including all clauses and decisions",
)
async def get_review_detail(review_id: str) -> ReviewDetailResponse:
    """Retrieve full review details, per-clause analyses, current decisions, and missing clauses."""
    review = get_review(review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review '{review_id}' not found.",
        )

    clauses_data = get_clause_analyses(review_id)
    latest_decisions = get_latest_decisions(review_id)
    counts = get_risk_counts_and_pending(review_id)

    clauses_with_decisions: List[ClauseWithDecision] = []
    for c in clauses_data:
        cid = c["clause_id"]
        analysis_dict = c.get("analysis", {})
        analysis = ClauseAnalysis.model_validate(analysis_dict)

        current_dec: Optional[ReviewDecisionRecord] = None
        if cid in latest_decisions:
            dec_dict = latest_decisions[cid]
            current_dec = ReviewDecisionRecord(
                decision_id=dec_dict["decision_id"],
                review_id=dec_dict["review_id"],
                clause_id=dec_dict["clause_id"],
                status=dec_dict["status"],
                reviewer_name=dec_dict["reviewer_name"],
                reviewer_note=dec_dict.get("reviewer_note"),
                final_text=dec_dict.get("final_text"),
                decided_at=dec_dict["decided_at"],
            )

        clauses_with_decisions.append(
            ClauseWithDecision(
                clause_id=cid,
                section_number=c.get("section_number"),
                title=c.get("title"),
                text=c["text"],
                analysis=analysis,
                current_decision=current_dec,
            )
        )

    return ReviewDetailResponse(
        review_id=review_id,
        contract_name=review["contract_name"],
        status=ReviewStatus(review["status"]),
        created_at=review["created_at"],
        finalized_at=review.get("finalized_at"),
        total_clauses=review.get("total_clauses", len(clauses_data)),
        analyzed_clauses=review.get("analyzed_clauses", len(clauses_data)),
        progress={
            "analyzed": review.get("analyzed_clauses", len(clauses_data)),
            "total": review.get("total_clauses", len(clauses_data)),
        },
        acceptable_count=counts["acceptable_count"],
        needs_negotiation_count=counts["needs_negotiation_count"],
        unacceptable_count=counts["unacceptable_count"],
        needs_human_review_count=counts["needs_human_review_count"],
        pending_decisions=counts["pending_decisions"],
        missing_clause_types=review.get("missing_clauses", []),
        clauses=clauses_with_decisions,
        error_message=review.get("error_message"),
        disclaimer=settings.LEGAL_DISCLAIMER,
    )


# ------------------------------------------------------------------------------
# 5. Clause Detail Endpoint
# ------------------------------------------------------------------------------


@router.get(
    "/reviews/{review_id}/clauses/{clause_id}",
    response_model=ClauseDetailResponse,
    summary="Get clause text, analysis, cited rules, and decision history",
)
async def get_clause_detail(review_id: str, clause_id: str) -> ClauseDetailResponse:
    """Retrieve full clause details, including resolved PlaybookRule objects and decision audit history."""
    review = get_review(review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review '{review_id}' not found.",
        )

    clause_row = get_clause_analysis(review_id, clause_id)
    if not clause_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause '{clause_id}' not found in review '{review_id}'.",
        )

    analysis_dict = clause_row.get("analysis", {})
    analysis = ClauseAnalysis.model_validate(analysis_dict)

    # Resolve full PlaybookRule objects from playbook service
    cited_rules: List[PlaybookRule] = []
    for rid in analysis.cited_rule_ids:
        rule = get_rule(rid)
        if rule and rule not in cited_rules:
            cited_rules.append(rule)

    # Fetch audit history of decisions
    history_rows = get_decisions_for_clause(review_id, clause_id)
    history = [
        ReviewDecisionRecord(
            decision_id=h["decision_id"],
            review_id=h["review_id"],
            clause_id=h["clause_id"],
            status=h["status"],
            reviewer_name=h["reviewer_name"],
            reviewer_note=h.get("reviewer_note"),
            final_text=h.get("final_text"),
            decided_at=h["decided_at"],
        )
        for h in history_rows
    ]
    current_decision = history[-1] if history else None

    # Compute word-level diffs
    redline_diff: Optional[List[DiffSegment]] = None
    if analysis.suggested_redline:
        redline_segs = compute_word_diff(clause_row["text"], analysis.suggested_redline)
        redline_diff = [DiffSegment.model_validate(s) for s in redline_segs]

    decision_diff: Optional[List[DiffSegment]] = None
    if current_decision and current_decision.final_text:
        dec_segs = compute_word_diff(clause_row["text"], current_decision.final_text)
        decision_diff = [DiffSegment.model_validate(s) for s in dec_segs]

    return ClauseDetailResponse(
        review_id=review_id,
        clause_id=clause_id,
        section_number=clause_row.get("section_number"),
        title=clause_row.get("title"),
        text=clause_row["text"],
        analysis=analysis,
        suggested_redline=analysis.suggested_redline,
        redline_diff=redline_diff,
        decision_diff=decision_diff,
        cited_rules=cited_rules,
        current_decision=current_decision,
        decision_history=history,
        disclaimer=settings.LEGAL_DISCLAIMER,
    )


# ------------------------------------------------------------------------------
# 6. Record Reviewer Decision Endpoint
# ------------------------------------------------------------------------------


@router.post(
    "/reviews/{review_id}/clauses/{clause_id}/decision",
    response_model=ReviewDecisionRecord,
    status_code=status.HTTP_200_OK,
    summary="Submit or modify reviewer decision on a clause (appends to audit log)",
)
async def submit_decision(
    review_id: str,
    clause_id: str,
    body: DecisionRequest,
) -> ReviewDecisionRecord:
    """Record an approved, edited, or rejected decision for a clause.

    Rules:
    - Reviewer name is required.
    - Final text is required when status is 'edited'.
    - Reviewer note is required when status is 'rejected'.
    - Decisions can be updated until the review is finalized (appends history).
    - Returns 409 Conflict if review is still processing or already finalized.
    - Returns 404 Not Found for unknown review or clause ID.
    """
    review = get_review(review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review '{review_id}' not found.",
        )

    review_status = review["status"]
    if review_status == ReviewStatus.PROCESSING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review is still processing. Please wait until analysis completes before recording decisions.",
        )

    if review_status == ReviewStatus.FINALIZED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review is already finalized and cannot be modified.",
        )

    clause_row = get_clause_analysis(review_id, clause_id)
    if not clause_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause '{clause_id}' not found in review '{review_id}'.",
        )

    record = add_decision(
        review_id=review_id,
        clause_id=clause_id,
        status=body.status.value,
        reviewer_name=body.reviewer_name,
        reviewer_note=body.reviewer_note,
        final_text=body.final_text,
    )

    return ReviewDecisionRecord(
        decision_id=record["decision_id"],
        review_id=record["review_id"],
        clause_id=record["clause_id"],
        status=record["status"],
        reviewer_name=record["reviewer_name"],
        reviewer_note=record.get("reviewer_note"),
        final_text=record.get("final_text"),
        decided_at=record["decided_at"],
    )


# ------------------------------------------------------------------------------
# 7. Finalize Review Endpoint
# ------------------------------------------------------------------------------


@router.post(
    "/reviews/{review_id}/finalize",
    response_model=FinalizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Finalize review and lock decisions (requires all necessary decisions)",
)
async def finalize_review(review_id: str) -> FinalizeResponse:
    """Finalize the review after verifying all required clauses have decisions.

    Rules:
    - Every clause rated Needs Negotiation or Unacceptable, or with needs_human_review=true,
      must have an approved, edited, or rejected decision.
    - If any required decisions are pending, returns 409 listing pending clause IDs.
    - If review is still processing or already finalized, returns 409 Conflict.
    - On success: resumes LangGraph checkpoint, updates status to finalized, and locks the review.
    """
    review = get_review(review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review '{review_id}' not found.",
        )

    review_status = review["status"]
    if review_status == ReviewStatus.PROCESSING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review is still processing. Cannot finalize before analysis completes.",
        )

    if review_status == ReviewStatus.FINALIZED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review is already finalized.",
        )

    # Validate that all required clauses have decisions
    pending_count, pending_clause_ids = get_pending_decisions(review_id)
    if pending_count > 0:
        detail_msg = {
            "message": f"Cannot finalize review: {pending_count} required clause(s) are pending review decisions: {', '.join(pending_clause_ids)}",
            "pending_clause_ids": pending_clause_ids,
            "pending_count": pending_count,
        }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_msg,
        )

    # Resume the LangGraph workflow
    try:
        await resume_contract_review_graph(review_id=review_id)
    except Exception as exc:
        logger.warning("Resuming graph checkpointer encountered: %s", exc)

    # Update database status to finalized
    now_iso = datetime.utcnow().isoformat()
    update_review_status(
        review_id=review_id,
        status=ReviewStatus.FINALIZED.value,
        finalized_at=now_iso,
    )

    logger.info("Review %s successfully finalized at %s", review_id, now_iso)

    return FinalizeResponse(
        review_id=review_id,
        status=ReviewStatus.FINALIZED,
        finalized_at=now_iso,
        message="Review finalized successfully. All clause decisions have been locked.",
        disclaimer=settings.LEGAL_DISCLAIMER,
    )


# ------------------------------------------------------------------------------
# 8. Report Generation & Export Endpoint
# ------------------------------------------------------------------------------


@router.get(
    "/reviews/{review_id}/report",
    summary="Generate deterministic review report in JSON, Markdown, or DOCX format",
)
async def get_review_report(
    review_id: str,
    format: str = Query("json", description="Export format: 'json', 'md', or 'docx'"),
) -> Any:
    """Generate and return comprehensive review report.

    Rules:
    - Reports can ONLY be generated for finalized reviews. If not finalized, returns 409 Conflict.
    - Deterministic and non-LLM: based entirely on persisted analyses and approved decisions.
    - Supported formats:
      - 'json': Structured ReviewReport Pydantic model.
      - 'md': Full GitHub-Flavored Markdown document.
      - 'docx': Microsoft Word document with colored visual diff formatting.
    """
    fmt = format.lower().strip()
    if fmt not in ("json", "md", "docx"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format '{format}'. Supported formats are 'json', 'md', and 'docx'.",
        )

    review = get_review(review_id)
    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review '{review_id}' not found.",
        )

    if review["status"] != ReviewStatus.FINALIZED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Report can only be generated for finalized reviews. Current review status is '{review['status']}'. "
                "Please ensure all required decisions are submitted and finalize the review before generating a report."
            ),
        )

    report = build_review_report(review_id)
    clean_stem = re.sub(r"[^a-zA-Z0-9_.-]", "_", Path(report.contract_name).stem)

    if fmt == "json":
        return report

    if fmt == "md":
        md_text = report_to_markdown(report)
        filename = f"{clean_stem}_Review_Report.md"
        return Response(
            content=md_text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    if fmt == "docx":
        docx_bytes = report_to_docx(report)
        filename = f"{clean_stem}_Review_Report.docx"
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

