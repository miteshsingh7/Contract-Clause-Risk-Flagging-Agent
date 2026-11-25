"""Deterministic non-LLM report builder service.

Compiles stored clause analyses, playbook rules, and human reviewer decisions
into the comprehensive ReviewReport model. Contains zero LLM invocations.
"""

from datetime import datetime
import logging
import re
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.models.schemas import (
    ClauseAnalysis,
    DecisionStatus,
    DiffSegment,
    PlaybookRule,
    ReportClauseItem,
    ReviewDecisionRecord,
    ReviewReport,
    RiskLevel,
)
from app.services.db import (
    get_clause_analyses,
    get_decisions_for_clause,
    get_latest_decisions,
    get_review,
)
from app.services.diff import compute_word_diff
from app.services.playbook import get_rule

logger = logging.getLogger(__name__)


def _natural_sort_key(clause_row: Dict[str, Any]) -> tuple:
    """Natural sort key for ordering clauses by section number and ID."""
    sec = str(clause_row.get("section_number") or "").strip()
    digits = re.findall(r"\d+", sec)
    digit_tuple = tuple(int(d) for d in digits) if digits else (999999,)
    return (digit_tuple, clause_row.get("clause_id", ""))


def build_review_report(
    review_id: str,
    db_path: Optional[str] = None,
) -> ReviewReport:
    """Build a deterministic ReviewReport object from SQLite persistence.

    Args:
        review_id: Unique review ID.
        db_path: Optional path to SQLite database.

    Returns:
        Populated ReviewReport model.

    Raises:
        ValueError: If review is not found.
    """
    review = get_review(review_id, db_path=db_path)
    if not review:
        raise ValueError(f"Review '{review_id}' not found.")

    contract_name = review.get("contract_name", "Untitled Contract")
    uploaded_at = review.get("created_at")
    finalized_at = review.get("finalized_at")
    missing_clause_types = review.get("missing_clauses", [])
    if isinstance(missing_clause_types, str):
        try:
            import json
            missing_clause_types = json.loads(missing_clause_types)
        except Exception:
            missing_clause_types = []

    # Retrieve all clauses and analyses
    clause_rows = get_clause_analyses(review_id, db_path=db_path)
    clause_rows.sort(key=_natural_sort_key)

    # Retrieve latest decisions
    latest_decisions = get_latest_decisions(review_id, db_path=db_path)

    # Gather full audit history for all clauses
    appendix_history: Dict[str, List[ReviewDecisionRecord]] = {}
    reviewers_set = set()

    for row in clause_rows:
        cid = row["clause_id"]
        history_rows = get_decisions_for_clause(review_id, cid, db_path=db_path)
        history_records = [
            ReviewDecisionRecord(
                decision_id=h["decision_id"],
                review_id=h["review_id"],
                clause_id=h["clause_id"],
                status=DecisionStatus(h["status"]),
                reviewer_name=h["reviewer_name"],
                reviewer_note=h.get("reviewer_note"),
                final_text=h.get("final_text"),
                decided_at=h["decided_at"],
            )
            for h in history_rows
        ]
        appendix_history[cid] = history_records
        for r in history_records:
            if r.reviewer_name:
                reviewers_set.add(r.reviewer_name.strip())

    reviewers_list = sorted(list(reviewers_set))

    # Counters
    acceptable_count = 0
    needs_negotiation_count = 0
    unacceptable_count = 0
    needs_human_review_count = 0
    approved_count = 0
    edited_count = 0
    rejected_count = 0

    report_clause_items: List[ReportClauseItem] = []
    all_analyses: List[ClauseAnalysis] = []

    for row in clause_rows:
        cid = row["clause_id"]
        sec_num = row.get("section_number")
        title = row.get("title")
        orig_text = row["text"]
        analysis_dict = row.get("analysis", {})

        analysis = ClauseAnalysis.model_validate(analysis_dict)
        all_analyses.append(analysis)

        # Risk counts
        if analysis.risk_level == RiskLevel.ACCEPTABLE:
            acceptable_count += 1
        elif analysis.risk_level == RiskLevel.NEEDS_NEGOTIATION:
            needs_negotiation_count += 1
        elif analysis.risk_level == RiskLevel.UNACCEPTABLE:
            unacceptable_count += 1

        if analysis.needs_human_review:
            needs_human_review_count += 1

        # Current decision
        current_dec_record: Optional[ReviewDecisionRecord] = None
        if cid in latest_decisions:
            d_dict = latest_decisions[cid]
            current_dec_record = ReviewDecisionRecord(
                decision_id=d_dict["decision_id"],
                review_id=d_dict["review_id"],
                clause_id=d_dict["clause_id"],
                status=DecisionStatus(d_dict["status"]),
                reviewer_name=d_dict["reviewer_name"],
                reviewer_note=d_dict.get("reviewer_note"),
                final_text=d_dict.get("final_text"),
                decided_at=d_dict["decided_at"],
            )
            if current_dec_record.status == DecisionStatus.APPROVED:
                approved_count += 1
            elif current_dec_record.status == DecisionStatus.EDITED:
                edited_count += 1
            elif current_dec_record.status == DecisionStatus.REJECTED:
                rejected_count += 1

        # Diffs
        redline_diff_segments: List[DiffSegment] = []
        if analysis.suggested_redline:
            redline_diff_raw = compute_word_diff(orig_text, analysis.suggested_redline)
            redline_diff_segments = [DiffSegment.model_validate(s) for s in redline_diff_raw]

        decision_diff_segments: Optional[List[DiffSegment]] = None
        if current_dec_record and current_dec_record.final_text:
            dec_diff_raw = compute_word_diff(orig_text, current_dec_record.final_text)
            decision_diff_segments = [DiffSegment.model_validate(s) for s in dec_diff_raw]

        # Resolve full PlaybookRule objects
        cited_rules: List[PlaybookRule] = []
        for rid in analysis.cited_rule_ids:
            rule_obj = get_rule(rid)
            if rule_obj and rule_obj not in cited_rules:
                cited_rules.append(rule_obj)

        # Resulting clause text rule logic (explicit rule e)
        if current_dec_record and current_dec_record.status == DecisionStatus.EDITED:
            resulting_text = current_dec_record.final_text or orig_text
            resulting_text_source = "final_text (edited by legal reviewer)"
        elif current_dec_record and current_dec_record.status == DecisionStatus.APPROVED:
            resulting_text = analysis.suggested_redline if analysis.suggested_redline else orig_text
            resulting_text_source = (
                "suggested_redline (approved by legal reviewer)"
                if analysis.suggested_redline
                else "original_text (approved by legal reviewer without modification)"
            )
        elif current_dec_record and current_dec_record.status == DecisionStatus.REJECTED:
            resulting_text = orig_text
            resulting_text_source = "original_text (suggested redline rejected by legal reviewer)"
        else:
            resulting_text = orig_text
            resulting_text_source = "original_text (compliant/no changes required)"

        item = ReportClauseItem(
            clause_id=cid,
            section_number=sec_num,
            title=title,
            clause_type=analysis.clause_type,
            risk_level=analysis.risk_level,
            confidence=analysis.confidence,
            needs_human_review=analysis.needs_human_review,
            review_reason=analysis.review_reason,
            original_text=orig_text,
            suggested_redline=analysis.suggested_redline,
            redline_diff=redline_diff_segments,
            cited_rules=cited_rules,
            explanation=analysis.explanation,
            decision=current_dec_record,
            decision_diff=decision_diff_segments,
            resulting_text=resulting_text,
            resulting_text_source=resulting_text_source,
        )
        report_clause_items.append(item)

    # Highest risk clauses (Unacceptable first, then Needs Negotiation)
    highest_risk: List[Dict[str, Any]] = []
    for item in report_clause_items:
        if item.risk_level == RiskLevel.UNACCEPTABLE:
            highest_risk.append({
                "clause_id": item.clause_id,
                "section_number": item.section_number,
                "title": item.title,
                "risk_level": item.risk_level.value,
                "clause_type": item.clause_type,
                "needs_human_review": item.needs_human_review,
            })
    for item in report_clause_items:
        if item.risk_level == RiskLevel.NEEDS_NEGOTIATION:
            highest_risk.append({
                "clause_id": item.clause_id,
                "section_number": item.section_number,
                "title": item.title,
                "risk_level": item.risk_level.value,
                "clause_type": item.clause_type,
                "needs_human_review": item.needs_human_review,
            })

    total_clauses = len(report_clause_items)

    # Construct executive summary text
    summary_text = (
        f"Contract review completed for '{contract_name}'. "
        f"A total of {total_clauses} substantive clause(s) were evaluated against the corporate negotiation playbook. "
        f"Risk breakdown: {acceptable_count} Acceptable, {needs_negotiation_count} Needs Negotiation, "
        f"{unacceptable_count} Unacceptable ({needs_human_review_count} flagged for human review). "
        f"Legal counsel recorded {approved_count} approved, {edited_count} edited, and {rejected_count} rejected decision(s). "
        f"{len(missing_clause_types)} playbook clause type(s) were omitted from the contract."
    )

    report_id = f"report-{review_id[:8]}"

    return ReviewReport(
        report_id=report_id,
        review_id=review_id,
        contract_name=contract_name,
        created_at=datetime.utcnow(),
        uploaded_at=uploaded_at,
        finalized_at=finalized_at,
        reviewers=reviewers_list,
        total_clauses=total_clauses,
        acceptable_count=acceptable_count,
        needs_negotiation_count=needs_negotiation_count,
        unacceptable_count=unacceptable_count,
        needs_human_review_count=needs_human_review_count,
        approved_count=approved_count,
        edited_count=edited_count,
        rejected_count=rejected_count,
        summary=summary_text,
        highest_risk_clauses=highest_risk,
        missing_clause_types=missing_clause_types,
        analyses=all_analyses,
        clauses=report_clause_items,
        appendix_decision_history=appendix_history,
        disclaimer=settings.LEGAL_DISCLAIMER,
    )
