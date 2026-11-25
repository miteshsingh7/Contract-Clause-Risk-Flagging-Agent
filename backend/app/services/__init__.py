"""Application services package."""

from app.services.db import (
    add_decision,
    create_review,
    get_clause_analysis,
    get_clause_analyses,
    get_db_connection,
    get_decisions_for_clause,
    get_latest_decision,
    get_latest_decisions,
    get_pending_decisions,
    get_review,
    init_db,
    list_reviews,
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

__all__ = [
    "add_decision",
    "build_review_report",
    "compute_word_diff",
    "create_review",
    "get_clause_analysis",
    "get_clause_analyses",
    "get_db_connection",
    "get_decisions_for_clause",
    "get_latest_decision",
    "get_latest_decisions",
    "get_pending_decisions",
    "get_review",
    "init_db",
    "list_reviews",
    "reconstruct_original",
    "reconstruct_revised",
    "report_to_docx",
    "report_to_json",
    "report_to_markdown",
    "save_clause_analyses",
    "update_review_status",
]
