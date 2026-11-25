"""SQLite persistence service for contract reviews, clause analyses, and decision audit logs.

Provides thread-safe access with foreign keys enabled, WAL journaling, and audit trailing.
The database serves as the source of truth for the API and frontend UI.
"""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional, Tuple

from app.core.config import settings
from app.models.schemas import Clause, ClauseAnalysis, RiskLevel

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# Connection & Initialization
# ------------------------------------------------------------------------------


@contextmanager
def get_db_connection(db_path: Optional[str] = None) -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection configured with WAL mode, busy timeout, and immediate transactions for writes."""
    target_path = Path(db_path or settings.DB_PATH).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(target_path),
        timeout=30.0,
        check_same_thread=False,
        isolation_level="IMMEDIATE",
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")

    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables and indexes if they do not already exist."""
    with get_db_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                contract_name TEXT NOT NULL,
                stored_file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                finalized_at TEXT,
                error_message TEXT,
                missing_clauses TEXT,
                total_clauses INTEGER DEFAULT 0,
                analyzed_clauses INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS clause_analyses (
                review_id TEXT NOT NULL,
                clause_id TEXT NOT NULL,
                section_number TEXT,
                title TEXT,
                text TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                PRIMARY KEY (review_id, clause_id),
                FOREIGN KEY (review_id) REFERENCES reviews (review_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS review_decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id TEXT NOT NULL,
                clause_id TEXT NOT NULL,
                status TEXT NOT NULL,
                reviewer_name TEXT NOT NULL,
                reviewer_note TEXT,
                final_text TEXT,
                decided_at TEXT NOT NULL,
                FOREIGN KEY (review_id) REFERENCES reviews (review_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_decisions_review_clause
            ON review_decisions (review_id, clause_id);
            """
        )
    logger.debug("Database initialized at %s", db_path or settings.DB_PATH)


# ------------------------------------------------------------------------------
# Review Lifecycle Operations
# ------------------------------------------------------------------------------


def create_review(
    review_id: str,
    contract_name: str,
    stored_file_path: str,
    db_path: Optional[str] = None,
) -> None:
    """Create a new contract review record in 'processing' status."""
    now_iso = datetime.utcnow().isoformat()
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reviews (
                review_id, contract_name, stored_file_path, status,
                created_at, finalized_at, error_message, missing_clauses,
                total_clauses, analyzed_clauses
            ) VALUES (?, ?, ?, 'processing', ?, NULL, NULL, '[]', 0, 0)
            """,
            (review_id, contract_name, stored_file_path, now_iso),
        )
    logger.info("Created review record %s for contract '%s'", review_id, contract_name)


def update_review_status(
    review_id: str,
    status: str,
    error_message: Optional[str] = None,
    finalized_at: Optional[str] = None,
    missing_clauses: Optional[List[str]] = None,
    total_clauses: Optional[int] = None,
    analyzed_clauses: Optional[int] = None,
    db_path: Optional[str] = None,
) -> None:
    """Update review status and progress metrics."""
    fields = ["status = ?"]
    params: List[Any] = [status]

    if error_message is not None:
        fields.append("error_message = ?")
        params.append(error_message)
    if finalized_at is not None:
        fields.append("finalized_at = ?")
        params.append(finalized_at)
    if missing_clauses is not None:
        fields.append("missing_clauses = ?")
        params.append(json.dumps(missing_clauses))
    if total_clauses is not None:
        fields.append("total_clauses = ?")
        params.append(total_clauses)
    if analyzed_clauses is not None:
        fields.append("analyzed_clauses = ?")
        params.append(analyzed_clauses)

    params.append(review_id)
    query = f"UPDATE reviews SET {', '.join(fields)} WHERE review_id = ?"

    with get_db_connection(db_path) as conn:
        conn.execute(query, params)
    logger.info("Updated review %s status to '%s'", review_id, status)


def get_review(review_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve review record by ID."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM reviews WHERE review_id = ?",
            (review_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        result = dict(row)
        if result.get("missing_clauses"):
            try:
                result["missing_clauses"] = json.loads(result["missing_clauses"])
            except Exception:
                result["missing_clauses"] = []
        else:
            result["missing_clauses"] = []
        return result


def list_reviews(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all reviews with aggregated risk counts and pending decision metrics."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM reviews ORDER BY created_at DESC"
        )
        rows = [dict(r) for r in cursor.fetchall()]

    summaries: List[Dict[str, Any]] = []
    for r in rows:
        rev_id = r["review_id"]
        counts = get_risk_counts_and_pending(rev_id, db_path=db_path)
        summary = {
            **r,
            **counts,
        }
        if summary.get("missing_clauses") and isinstance(summary["missing_clauses"], str):
            try:
                summary["missing_clauses"] = json.loads(summary["missing_clauses"])
            except Exception:
                summary["missing_clauses"] = []
        summaries.append(summary)

    return summaries


# ------------------------------------------------------------------------------
# Clause Analysis Operations
# ------------------------------------------------------------------------------


def save_clause_analyses(
    review_id: str,
    clauses: List[Clause],
    analyses: List[ClauseAnalysis],
    missing_clauses: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> None:
    """Batch save clause analyses and update review clause totals."""
    analyses_by_id = {a.clause_id: a for a in analyses}

    with get_db_connection(db_path) as conn:
        for clause in clauses:
            analysis = analyses_by_id.get(clause.id)
            analysis_json = analysis.model_dump_json() if analysis else "{}"
            conn.execute(
                """
                INSERT OR REPLACE INTO clause_analyses (
                    review_id, clause_id, section_number, title, text, analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    clause.id,
                    clause.section_number,
                    clause.title,
                    clause.text,
                    analysis_json,
                ),
            )

        # Update totals and missing clauses on review
        missing_json = json.dumps(missing_clauses or [])
        conn.execute(
            """
            UPDATE reviews SET
                total_clauses = ?,
                analyzed_clauses = ?,
                missing_clauses = ?
            WHERE review_id = ?
            """,
            (len(clauses), len(analyses), missing_json, review_id),
        )

    logger.info(
        "Persisted %d clauses and %d analyses for review %s",
        len(clauses),
        len(analyses),
        review_id,
    )


def get_clause_analyses(review_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all clauses and analyses for a review."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM clause_analyses
            WHERE review_id = ?
            ORDER BY clause_id ASC
            """,
            (review_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]

    for r in rows:
        try:
            r["analysis"] = json.loads(r["analysis_json"])
        except Exception:
            r["analysis"] = {}
    return rows


def get_clause_analysis(
    review_id: str,
    clause_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve an individual clause analysis by review ID and clause ID."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM clause_analyses
            WHERE review_id = ? AND clause_id = ?
            """,
            (review_id, clause_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        result = dict(row)
        try:
            result["analysis"] = json.loads(result["analysis_json"])
        except Exception:
            result["analysis"] = {}
        return result


# ------------------------------------------------------------------------------
# Review Decisions & Audit Trail Operations
# ------------------------------------------------------------------------------


def add_decision(
    review_id: str,
    clause_id: str,
    status: str,
    reviewer_name: str,
    reviewer_note: Optional[str] = None,
    final_text: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a human legal reviewer decision event to the audit trail."""
    now_iso = datetime.utcnow().isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO review_decisions (
                review_id, clause_id, status, reviewer_name,
                reviewer_note, final_text, decided_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                clause_id,
                status,
                reviewer_name,
                reviewer_note,
                final_text,
                now_iso,
            ),
        )
        decision_id = cursor.lastrowid

    logger.info(
        "Recorded decision %d (%s) for clause %s in review %s by %s",
        decision_id,
        status,
        clause_id,
        review_id,
        reviewer_name,
    )
    return {
        "decision_id": decision_id,
        "review_id": review_id,
        "clause_id": clause_id,
        "status": status,
        "reviewer_name": reviewer_name,
        "reviewer_note": reviewer_note,
        "final_text": final_text,
        "decided_at": now_iso,
    }


def get_decisions_for_clause(
    review_id: str,
    clause_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve full append-only decision audit history for a clause."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM review_decisions
            WHERE review_id = ? AND clause_id = ?
            ORDER BY decision_id ASC
            """,
            (review_id, clause_id),
        )
        return [dict(r) for r in cursor.fetchall()]


def get_latest_decision(
    review_id: str,
    clause_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve the current (latest) decision for a clause."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM review_decisions
            WHERE review_id = ? AND clause_id = ?
            ORDER BY decision_id DESC
            LIMIT 1
            """,
            (review_id, clause_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_latest_decisions(
    review_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Retrieve a mapping of clause_id -> latest decision dict for all clauses in a review."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT rd.* FROM review_decisions rd
            INNER JOIN (
                SELECT clause_id, MAX(decision_id) as max_id
                FROM review_decisions
                WHERE review_id = ?
                GROUP BY clause_id
            ) latest ON rd.clause_id = latest.clause_id AND rd.decision_id = latest.max_id
            WHERE rd.review_id = ?
            """,
            (review_id, review_id),
        )
        return {r["clause_id"]: dict(r) for r in cursor.fetchall()}


# ------------------------------------------------------------------------------
# Risk Counts & Pending Decision Logic
# ------------------------------------------------------------------------------


def clause_requires_decision(analysis_dict: Dict[str, Any]) -> bool:
    """Determine whether a clause requires human reviewer decision approval.

    Per playbook rules:
    - Clauses rated Needs Negotiation or Unacceptable REQUIRE a decision.
    - Clauses flagged with needs_human_review=True REQUIRE a decision.
    - Clauses rated Acceptable WITHOUT needs_human_review do NOT require a decision.
    """
    risk = analysis_dict.get("risk_level")
    needs_review = bool(analysis_dict.get("needs_human_review", False))

    if risk in (RiskLevel.NEEDS_NEGOTIATION.value, RiskLevel.UNACCEPTABLE.value):
        return True
    if needs_review:
        return True
    return False


def get_pending_decisions(
    review_id: str,
    db_path: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """Return the count and list of clause IDs requiring a decision that do not yet have one."""
    clauses = get_clause_analyses(review_id, db_path=db_path)
    latest_decisions = get_latest_decisions(review_id, db_path=db_path)

    pending_ids: List[str] = []
    for c in clauses:
        analysis = c.get("analysis", {})
        if clause_requires_decision(analysis):
            cid = c["clause_id"]
            if cid not in latest_decisions:
                pending_ids.append(cid)

    return len(pending_ids), pending_ids


def get_risk_counts_and_pending(
    review_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, int]:
    """Calculate aggregate risk level counts and pending decisions for a review."""
    clauses = get_clause_analyses(review_id, db_path=db_path)
    latest_decisions = get_latest_decisions(review_id, db_path=db_path)

    acceptable = 0
    needs_neg = 0
    unacceptable = 0
    human_review = 0
    pending_count = 0

    for c in clauses:
        analysis = c.get("analysis", {})
        risk = analysis.get("risk_level")
        needs_rev = bool(analysis.get("needs_human_review", False))

        if risk == RiskLevel.ACCEPTABLE.value:
            acceptable += 1
        elif risk == RiskLevel.NEEDS_NEGOTIATION.value:
            needs_neg += 1
        elif risk == RiskLevel.UNACCEPTABLE.value:
            unacceptable += 1

        if needs_rev:
            human_review += 1

        if clause_requires_decision(analysis):
            if c["clause_id"] not in latest_decisions:
                pending_count += 1

    return {
        "acceptable_count": acceptable,
        "needs_negotiation_count": needs_neg,
        "unacceptable_count": unacceptable,
        "needs_human_review_count": human_review,
        "pending_decisions": pending_count,
    }


def has_active_processing_reviews(db_path: Optional[str] = None) -> bool:
    """Check if any contract review is currently in 'processing' status."""
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) as count FROM reviews WHERE status = 'processing'"
        )
        row = cursor.fetchone()
        return bool(row and row["count"] > 0)

