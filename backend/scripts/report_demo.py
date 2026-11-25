"""CLI script to generate, export, and inspect contract review reports.

Usage:
  # Seed a complete demo review and export reports in all formats
  python3 backend/scripts/report_demo.py --seed

  # Export reports for an existing finalized review ID
  python3 backend/scripts/report_demo.py <review_id> --format md
  python3 backend/scripts/report_demo.py <review_id> --format docx
  python3 backend/scripts/report_demo.py <review_id> --format all
"""

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import uuid

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.models.schemas import (
    Clause,
    ClauseAnalysis,
    DecisionStatus,
    RiskLevel,
)
from app.services.db import (
    add_decision,
    create_review,
    get_review,
    init_db,
    save_clause_analyses,
    update_review_status,
)
from app.services.report import build_review_report
from app.services.report_export import (
    report_to_docx,
    report_to_json,
    report_to_markdown,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("report_demo")


def seed_awaiting_review(db_path: Path) -> str:
    """Seed a synthetic review in awaiting_review state with NO decisions for testing the review flow."""
    init_db(str(db_path))
    review_id = f"demo-awaiting-{uuid.uuid4().hex[:8]}"
    contract_name = "sample_contract_needs_negotiation.docx"
    stored_path = str(backend_dir / "data" / "samples" / contract_name)

    create_review(
        review_id=review_id,
        contract_name=contract_name,
        stored_file_path=stored_path,
        db_path=str(db_path),
    )

    clauses = [
        Clause(
            id="C-001",
            section_number="1",
            title="Limitation of Liability",
            text=(
                "1. Limitation of Liability. 1.1 In no event shall either party's aggregate liability "
                "arising out of or related to this Agreement exceed six (6) months of fees paid."
            ),
        ),
        Clause(
            id="C-002",
            section_number="2",
            title="Indemnification",
            text=(
                "2. Indemnification. 2.1 Customer shall defend and indemnify Company against all third-party "
                "claims arising from Customer's use of the Services. Company provides no indemnity to Customer."
            ),
        ),
        Clause(
            id="C-003",
            section_number="3",
            title="Term and Termination",
            text=(
                "3. Term and Termination. 3.1 Either party may terminate this Agreement without cause upon "
                "sixty (60) days prior written notice."
            ),
        ),
        Clause(
            id="C-004",
            section_number="4",
            title="Confidentiality",
            text=(
                "4. Confidentiality. 4.1 'Confidential Information' means all non-public information disclosed by "
                "one party to the other. Each party agrees to protect such information using reasonable care for five (5) years."
            ),
        ),
        Clause(
            id="C-005",
            section_number="5",
            title="Governing Law and Jurisdiction",
            text=(
                "5. Governing Law and Jurisdiction. 5.1 This Agreement shall be governed by English law and "
                "subject to the exclusive jurisdiction of the courts of London, England."
            ),
        ),
    ]

    analyses = [
        ClauseAnalysis(
            clause_id="C-001",
            clause_type="limitation_of_liability",
            risk_level=RiskLevel.NEEDS_NEGOTIATION,
            cited_rule_ids=["LOL-01"],
            explanation="Cap of 6 months fees is within acceptable fallback, but standard position requires 12 months fees.",
            suggested_redline=(
                "1. Limitation of Liability. 1.1 In no event shall either party's aggregate liability "
                "arising out of or related to this Agreement exceed twelve (12) months of fees paid."
            ),
            confidence=0.92,
            needs_human_review=True,
            review_reason="Liability cap deviates from standard position",
        ),
        ClauseAnalysis(
            clause_id="C-002",
            clause_type="indemnification",
            risk_level=RiskLevel.UNACCEPTABLE,
            cited_rule_ids=["IND-01"],
            explanation="Unilateral customer indemnification with zero supplier indemnity violates core company mutual-indemnity position.",
            suggested_redline=(
                "2. Indemnification. 2.1 Each party shall defend and indemnify the other party against third-party claims "
                "arising from its material breach or willful misconduct."
            ),
            confidence=0.95,
            needs_human_review=True,
            review_reason="Unilateral indemnity policy violation",
        ),
        ClauseAnalysis(
            clause_id="C-003",
            clause_type="termination",
            risk_level=RiskLevel.NEEDS_NEGOTIATION,
            cited_rule_ids=["TRM-01"],
            explanation="60-day notice for convenience is outside standard 30-day position, but within 60-day acceptable fallback.",
            suggested_redline=(
                "3. Term and Termination. 3.1 Either party may terminate this Agreement without cause upon "
                "thirty (30) days prior written notice."
            ),
            confidence=0.89,
        ),
        ClauseAnalysis(
            clause_id="C-004",
            clause_type="confidentiality",
            risk_level=RiskLevel.ACCEPTABLE,
            cited_rule_ids=["CONF-01"],
            explanation="Mutual confidentiality with reasonable care and standard 5-year duration satisfies standard position.",
            suggested_redline=None,
            confidence=0.98,
        ),
        ClauseAnalysis(
            clause_id="C-005",
            clause_type="governing_law",
            risk_level=RiskLevel.UNACCEPTABLE,
            cited_rule_ids=["GOV-01"],
            explanation="Foreign English law and London jurisdiction violates mandatory home-jurisdiction policy trigger.",
            suggested_redline=(
                "5. Governing Law and Jurisdiction. 5.1 This Agreement shall be governed by the laws of the State of Delaware, "
                "without regard to conflicts of law principles, with exclusive jurisdiction in New Castle County, Delaware."
            ),
            confidence=0.94,
            needs_human_review=True,
            review_reason="Foreign governing law policy violation",
        ),
    ]

    missing_types = ["ip_ownership", "payment_terms", "auto_renewal", "data_protection", "assignment"]

    save_clause_analyses(
        review_id=review_id,
        clauses=clauses,
        analyses=analyses,
        missing_clauses=missing_types,
        db_path=str(db_path),
    )

    update_review_status(
        review_id=review_id,
        status="awaiting_review",
        missing_clauses=missing_types,
        total_clauses=len(clauses),
        analyzed_clauses=len(analyses),
        db_path=str(db_path),
    )

    return review_id


def seed_demo_review(db_path: Path) -> str:
    """Seed a synthetic finalized review with a realistic mix of approved, edited, and rejected decisions."""
    init_db(str(db_path))
    review_id = f"demo-{uuid.uuid4().hex[:8]}"
    contract_name = "sample_contract_needs_negotiation.docx"
    stored_path = str(backend_dir / "data" / "samples" / contract_name)

    create_review(
        review_id=review_id,
        contract_name=contract_name,
        stored_file_path=stored_path,
        db_path=str(db_path),
    )

    # Synthetic clauses representing various negotiation scenarios
    clauses = [
        Clause(
            id="C-001",
            section_number="1",
            title="Limitation of Liability",
            text=(
                "1. Limitation of Liability. 1.1 In no event shall either party's aggregate liability "
                "arising out of or related to this Agreement exceed six (6) months of fees paid."
            ),
        ),
        Clause(
            id="C-002",
            section_number="2",
            title="Indemnification",
            text=(
                "2. Indemnification. 2.1 Customer shall defend and indemnify Company against all third-party "
                "claims arising from Customer's use of the Services. Company provides no indemnity to Customer."
            ),
        ),
        Clause(
            id="C-003",
            section_number="3",
            title="Term and Termination",
            text=(
                "3. Term and Termination. 3.1 Either party may terminate this Agreement without cause upon "
                "sixty (60) days prior written notice."
            ),
        ),
        Clause(
            id="C-004",
            section_number="4",
            title="Confidentiality",
            text=(
                "4. Confidentiality. 4.1 Each party agrees to hold all confidential information of the other "
                "in confidence using at least reasonable care for five (5) years following termination."
            ),
        ),
        Clause(
            id="C-005",
            section_number="5",
            title="Governing Law and Jurisdiction",
            text=(
                "5. Governing Law and Jurisdiction. 5.1 This Agreement is governed by the laws of England and "
                "Wales, and disputes shall be resolved exclusively in the courts of London, UK."
            ),
        ),
    ]

    analyses = [
        ClauseAnalysis(
            clause_id="C-001",
            clause_type="limitation_of_liability",
            risk_level=RiskLevel.NEEDS_NEGOTIATION,
            cited_rule_ids=["LOL-01"],
            explanation="Liability cap of 6 months fees is below standard position (12 months), but acceptable under fallback.",
            suggested_redline=(
                "1. Limitation of Liability. 1.1 In no event shall either party's aggregate liability "
                "arising out of or related to this Agreement exceed twelve (12) months of fees paid or payable."
            ),
            confidence=0.92,
        ),
        ClauseAnalysis(
            clause_id="C-002",
            clause_type="indemnification",
            risk_level=RiskLevel.UNACCEPTABLE,
            cited_rule_ids=["IND-01"],
            explanation="Unilateral indemnification where Customer indemnifies Company but Company provides zero IP indemnity hits unacceptable trigger.",
            suggested_redline=(
                "2. Indemnification. 2.1 Mutual Indemnification. Company shall defend and indemnify Customer against IP infringement claims. "
                "Customer shall defend and indemnify Company against third-party claims arising from unauthorized data use."
            ),
            confidence=0.96,
            needs_human_review=True,
            review_reason="Unilateral indemnification trigger hit",
        ),
        ClauseAnalysis(
            clause_id="C-003",
            clause_type="termination",
            risk_level=RiskLevel.NEEDS_NEGOTIATION,
            cited_rule_ids=["TRM-01"],
            explanation="60-day notice for convenience exceeds standard 30-day notice but falls within 60-day acceptable fallback.",
            suggested_redline=(
                "3. Term and Termination. 3.1 Either party may terminate this Agreement without cause upon "
                "thirty (30) days prior written notice."
            ),
            confidence=0.89,
        ),
        ClauseAnalysis(
            clause_id="C-004",
            clause_type="confidentiality",
            risk_level=RiskLevel.ACCEPTABLE,
            cited_rule_ids=["CONF-01"],
            explanation="Mutual confidentiality with reasonable care and standard 5-year duration satisfies standard position.",
            suggested_redline=None,
            confidence=0.98,
        ),
        ClauseAnalysis(
            clause_id="C-005",
            clause_type="governing_law",
            risk_level=RiskLevel.UNACCEPTABLE,
            cited_rule_ids=["GOV-01"],
            explanation="Foreign English law and London jurisdiction violates mandatory home-jurisdiction policy trigger.",
            suggested_redline=(
                "5. Governing Law and Jurisdiction. 5.1 This Agreement shall be governed by the laws of the State of Delaware, "
                "without regard to conflicts of law principles, with exclusive jurisdiction in New Castle County, Delaware."
            ),
            confidence=0.94,
            needs_human_review=True,
            review_reason="Foreign governing law policy violation",
        ),
    ]

    missing_types = ["ip_ownership", "payment_terms", "auto_renewal", "data_protection", "assignment"]

    save_clause_analyses(
        review_id=review_id,
        clauses=clauses,
        analyses=analyses,
        missing_clauses=missing_types,
        db_path=str(db_path),
    )

    update_review_status(
        review_id=review_id,
        status="awaiting_review",
        missing_clauses=missing_types,
        total_clauses=len(clauses),
        analyzed_clauses=len(analyses),
        db_path=str(db_path),
    )

    # 1. Superseded decision on C-001 (Audit Trail Demo)
    add_decision(
        review_id=review_id,
        clause_id="C-001",
        status=DecisionStatus.REJECTED.value,
        reviewer_name="Associate Jordan",
        reviewer_note="Initial thought to reject 6-month cap.",
        db_path=str(db_path),
    )
    # Final active decision on C-001: EDITED
    add_decision(
        review_id=review_id,
        clause_id="C-001",
        status=DecisionStatus.EDITED.value,
        reviewer_name="Lead Counsel Sarah Jenkins",
        reviewer_note="Negotiated compromise: 12 months fees with $1M minimum ceiling.",
        final_text=(
            "1. Limitation of Liability. 1.1 In no event shall either party's aggregate liability "
            "exceed the greater of $1,000,000 or total fees paid in the preceding twelve (12) months."
        ),
        db_path=str(db_path),
    )

    # 2. Approved decision on C-002: APPROVED AI redline
    add_decision(
        review_id=review_id,
        clause_id="C-002",
        status=DecisionStatus.APPROVED.value,
        reviewer_name="Lead Counsel Sarah Jenkins",
        reviewer_note="Approved mutual indemnification language suggested by playbook agent.",
        db_path=str(db_path),
    )

    # 3. Rejected decision on C-003: REJECTED redline (accepted counterparty 60 days)
    add_decision(
        review_id=review_id,
        clause_id="C-003",
        status=DecisionStatus.REJECTED.value,
        reviewer_name="Associate Jordan",
        reviewer_note="Counterparty refused 30 days. Business approved 60 days per acceptable fallback TRM-01.",
        db_path=str(db_path),
    )

    # 4. Edited decision on C-005: EDITED foreign governing law
    add_decision(
        review_id=review_id,
        clause_id="C-005",
        status=DecisionStatus.EDITED.value,
        reviewer_name="Lead Counsel Sarah Jenkins",
        reviewer_note="Amended to New York law per global corporate fallback agreement.",
        final_text=(
            "5. Governing Law and Jurisdiction. 5.1 This Agreement shall be governed by and construed in accordance "
            "with the laws of the State of New York, USA, without regard to conflicts of law provisions."
        ),
        db_path=str(db_path),
    )

    # Finalize the review
    update_review_status(
        review_id=review_id,
        status="finalized",
        finalized_at=datetime.utcnow().isoformat(),
        db_path=str(db_path),
    )

    return review_id


def export_reports(review_id: str, format_choice: str, db_path: Path, output_dir: Path) -> List[Path]:
    """Build review report and write to data/reports/ in requested formats."""
    report = build_review_report(review_id, db_path=str(db_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_name = report.contract_name.replace(".docx", "").replace(".pdf", "")

    exported_files: List[Path] = []
    formats = ["md", "docx", "json"] if format_choice == "all" else [format_choice]

    for fmt in formats:
        if fmt == "md":
            md_path = output_dir / f"{clean_name}_{report.report_id}.md"
            md_content = report_to_markdown(report)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
            exported_files.append(md_path)
            logger.info("Generated Markdown Report: %s", md_path)

        elif fmt == "docx":
            docx_path = output_dir / f"{clean_name}_{report.report_id}.docx"
            docx_bytes = report_to_docx(report)
            with open(docx_path, "wb") as f:
                f.write(docx_bytes)
            exported_files.append(docx_path)
            logger.info("Generated DOCX Report: %s", docx_path)

        elif fmt == "json":
            json_path = output_dir / f"{clean_name}_{report.report_id}.json"
            json_content = report_to_json(report)
            with open(json_path, "w", encoding="utf-8") as f:
                f.write(json_content)
            exported_files.append(json_path)
            logger.info("Generated JSON Report: %s", json_path)

    return exported_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and export review reports.")
    parser.add_argument("review_id", nargs="?", default=None, help="ID of finalized review in local DB")
    parser.add_argument(
        "--format",
        "-f",
        default="all",
        choices=["md", "docx", "json", "all"],
        help="Export format (default: all)",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Create a synthetic finalized review with approvals/edits/rejections for instant demonstration",
    )
    parser.add_argument(
        "--seed-awaiting",
        action="store_true",
        help="Create a synthetic review in 'awaiting_review' state with 0 decisions, printing the frontend review URL",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:5173",
        help="Frontend base URL for review links (default: http://localhost:5173)",
    )
    args = parser.parse_args()

    db_path = Path(settings.DB_PATH).resolve()
    reports_dir = backend_dir / "data" / "reports"

    if args.seed_awaiting:
        target_id = seed_awaiting_review(db_path)
        clean_url = args.base_url.rstrip("/")
        frontend_url = f"{clean_url}/reviews/{target_id}"
        print("\n" + "=" * 80)
        print("SEEDED REVIEW IN AWAITING_REVIEW STATE (ZERO DECISIONS)")
        print("=" * 80)
        print(f"Review ID:        {target_id}")
        print(f"Contract:         sample_contract_needs_negotiation.docx")
        print(f"Status:           awaiting_review")
        print(f"Clauses:          5 substantive clauses (4 flagged for review)")
        print(f"Decisions:        0 / 5 decided (5 pending decisions)")
        print(f"Frontend URL:     {frontend_url}")
        print("=" * 80)
        print("\nOpen the frontend URL to test approving, editing, rejecting, and finalizing!\n")
        return

    target_id = args.review_id

    if args.seed or not target_id:
        print("\n[+] Seeding synthetic finalized contract review with approved, edited, and rejected decisions...")
        target_id = seed_demo_review(db_path)
        print(f"[+] Demo Review Created: {target_id}\n")

    review = get_review(target_id, db_path=str(db_path))
    if not review:
        print(f"[-] Error: Review '{target_id}' not found in database {db_path}.")
        sys.exit(1)

    if review["status"] != "finalized":
        print(f"[-] Error: Review '{target_id}' is in status '{review['status']}'.")
        print("    Reports may only be generated for finalized reviews.")
        sys.exit(1)

    print(f"Generating reports for review: {target_id} ({review['contract_name']})")
    files = export_reports(target_id, args.format, db_path, reports_dir)

    print("\n" + "=" * 80)
    print("REPORT GENERATION COMPLETE")
    print("=" * 80)
    for f in files:
        print(f"  - [{f.suffix.upper()[1:]}] {f}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
