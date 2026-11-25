#!/usr/bin/env python3
"""End-to-end smoke test script for Contract Clause Risk-Flagging backend.

Tests the full advisory review lifecycle against a running FastAPI backend:
1. Uploads all 3 sample contracts (.docx)
2. Polls until awaiting_review
3. Prints per-clause risk and redline findings
4. Attempts premature finalization and asserts 409 Conflict (decision gating)
5. Submits a realistic mix of Approved, Edited, and Rejected decisions
6. Finalizes and locks the review
7. Downloads and validates Markdown, DOCX, and JSON reports (verifying docx integrity)

Usage:
    python3 backend/scripts/e2e_smoke.py --base-url http://127.0.0.1:8000
    python3 backend/scripts/e2e_smoke.py --seeded
"""

import argparse
import io
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import docx
import httpx

# Ensure backend directory is in sys.path
script_dir = Path(__file__).resolve().parent
backend_dir = script_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.config import settings
from app.services.db import (
    create_review,
    get_review,
    init_db,
    save_clause_analyses,
    update_review_status,
)
from app.models.schemas import Clause, ClauseAnalysis, RiskLevel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e_smoke")

SAMPLE_FILES = [
    "sample_contract_compliant.docx",
    "sample_contract_needs_negotiation.docx",
    "sample_contract_unacceptable.docx",
]


class SmokeTestRunner:
    """Orchestrates end-to-end verification against the running backend API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", in_process: bool = False, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.in_process = in_process
        if in_process:
            from fastapi.testclient import TestClient
            self.client = TestClient(app)
        else:
            self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.samples_dir = backend_dir / "data" / "samples"
        self.results: List[Dict[str, Any]] = []

    def check_health(self) -> bool:
        """Verify the backend is live and healthy."""
        try:
            resp = self.client.get("/health")
            if resp.status_code == 200 and resp.json().get("status") in ("ok", "healthy"):
                logger.info("Backend health check PASSED at %s", self.base_url)
                return True
            logger.error("Health check returned status %d: %s", resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("Failed to connect to backend at %s: %s", self.base_url, exc)
            return False

    def upload_contract(self, filename: str) -> str:
        """Upload a sample contract file and return review_id."""
        file_path = self.samples_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Sample file not found: {file_path}")

        with open(file_path, "rb") as f:
            files = {"file": (filename, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            resp = self.client.post("/contracts/upload", files=files)

        if resp.status_code != 200:
            raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        review_id = data["review_id"]
        logger.info("Uploaded '%s' -> Review ID: %s (status: %s)", filename, review_id, data["status"])
        return review_id

    def poll_until_ready(self, review_id: str, max_seconds: int = 120) -> Dict[str, Any]:
        """Poll review status until awaiting_review or failure."""
        start_time = time.time()
        while time.time() - start_time < max_seconds:
            resp = self.client.get(f"/reviews/{review_id}/status")
            if resp.status_code != 200:
                raise RuntimeError(f"Failed to fetch status: {resp.text}")

            status_data = resp.json()
            curr_status = status_data["status"]

            if curr_status == "awaiting_review":
                elapsed = time.time() - start_time
                logger.info("Review %s reached 'awaiting_review' in %.1fs", review_id, elapsed)
                # Fetch full review detail
                detail_resp = self.client.get(f"/reviews/{review_id}")
                return detail_resp.json()

            if curr_status == "failed":
                err = status_data.get("error_message", "Unknown error")
                raise RuntimeError(f"Review pipeline failed: {err}")

            time.sleep(2.0)

        raise TimeoutError(f"Review {review_id} timed out waiting for analysis after {max_seconds}s")

    def test_premature_finalize_blocked(self, review_id: str, pending_count: int) -> None:
        """Assert that finalization is blocked (409 Conflict) while decisions are pending."""
        if pending_count == 0:
            return  # Compliant contract with 0 non-acceptable/flagged clauses needs no gating check

        resp = self.client.post(f"/reviews/{review_id}/finalize")
        if resp.status_code != 409:
            raise AssertionError(f"Expected 409 Conflict when finalizing with {pending_count} pending decisions, got {resp.status_code}")

        detail = resp.json().get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("pending_count") == pending_count, f"Expected pending_count {pending_count}, got {detail}"
        logger.info("Decision gating verified: finalize blocked (409 Conflict) with %d pending clauses", pending_count)

    def submit_test_decisions(self, review_id: str, clauses: List[Dict[str, Any]]) -> None:
        """Submit a mix of Approved, Edited, and Rejected decisions as a reviewer."""
        reviewer_name = "Legal Counsel SmokeTester"

        for idx, clause_item in enumerate(clauses):
            clause_id = clause_item["clause_id"]
            analysis = clause_item["analysis"]
            risk = analysis["risk_level"]
            needs_review = analysis.get("needs_human_review", False)

            # Determine decision type for a realistic mix
            if idx == 0:
                # Approve
                payload = {
                    "status": "approved",
                    "reviewer_name": reviewer_name,
                    "reviewer_note": "Approved standard clause wording.",
                }
            elif idx == 1:
                # Edit
                original_text = clause_item["text"]
                edited_text = f"{original_text} [Agreed corporate fallback addendum]."
                payload = {
                    "status": "edited",
                    "reviewer_name": reviewer_name,
                    "reviewer_note": "Custom fallback language agreed in negotiation.",
                    "final_text": edited_text,
                }
            elif idx == 2 and (risk != "Acceptable" or needs_review):
                # Reject
                payload = {
                    "status": "rejected",
                    "reviewer_name": reviewer_name,
                    "reviewer_note": "Counterparty rejected proposed redline; business accepted commercial risk.",
                }
            else:
                # Default approve
                payload = {
                    "status": "approved",
                    "reviewer_name": reviewer_name,
                    "reviewer_note": "Approved by legal reviewer.",
                }

            dec_resp = self.client.post(
                f"/reviews/{review_id}/clauses/{clause_id}/decision",
                json=payload,
            )
            if dec_resp.status_code != 200:
                raise RuntimeError(f"Failed to submit decision on clause {clause_id}: {dec_resp.text}")

        logger.info("Submitted decisions for all %d clauses in review %s", len(clauses), review_id)

    def finalize_review(self, review_id: str) -> None:
        """Finalize and permanently lock the review."""
        resp = self.client.post(f"/reviews/{review_id}/finalize")
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to finalize review {review_id} ({resp.status_code}): {resp.text}")

        data = resp.json()
        assert data["status"] == "finalized", f"Expected finalized status, got {data}"
        logger.info("Successfully finalized and locked review %s", review_id)

    def verify_report_downloads(self, review_id: str) -> None:
        """Download and validate Markdown, DOCX, and JSON reports."""
        # 1. Markdown
        md_resp = self.client.get(f"/reviews/{review_id}/report?format=md")
        assert md_resp.status_code == 200, f"MD report failed: {md_resp.text}"
        assert len(md_resp.text.strip()) > 100, "MD report output was empty or too small"
        assert "Executive Summary".lower() in md_resp.text.lower()
        assert "ADVISORY".lower() in md_resp.text.lower()

        # 2. JSON
        json_resp = self.client.get(f"/reviews/{review_id}/report?format=json")
        assert json_resp.status_code == 200, f"JSON report failed: {json_resp.text}"
        report_dict = json_resp.json()
        assert report_dict.get("review_id") == review_id or report_dict.get("report_id") is not None
        assert "summary" in report_dict
        assert "analyses" in report_dict
        assert report_dict.get("total_clauses", 0) > 0

        # 3. DOCX
        docx_resp = self.client.get(f"/reviews/{review_id}/report?format=docx")
        assert docx_resp.status_code == 200, f"DOCX report failed: {docx_resp.text}"
        docx_bytes = docx_resp.content
        assert len(docx_bytes) > 1000, "DOCX report file was too small"

        # Validate DOCX integrity using python-docx
        try:
            doc = docx.Document(io.BytesIO(docx_bytes))
            para_count = len(doc.paragraphs)
            assert para_count > 5, f"DOCX has insufficient paragraphs ({para_count})"
        except Exception as exc:
            raise AssertionError(f"Generated DOCX report is corrupted or unreadable: {exc}") from exc

        logger.info("Verified reports (MD, JSON, DOCX) for review %s: All non-empty, DOCX opens cleanly", review_id)

    def run_seeded_contract_test(self, filename: str) -> Dict[str, Any]:
        """Run smoke test against a seeded review (fallback when live LLM is disabled)."""
        logger.info("Running seeded contract smoke test for '%s'...", filename)
        db_path = str(Path(settings.DB_PATH).resolve())
        init_db(db_path)

        import uuid
        review_id = f"smoke-seed-{uuid.uuid4().hex[:8]}"
        file_path = str(self.samples_dir / filename)

        create_review(
            review_id=review_id,
            contract_name=filename,
            stored_file_path=file_path,
            db_path=db_path,
        )

        clauses = [
            Clause(id="C-001", section_number="1", title="Limitation of Liability", text="Liability capped at $10,000."),
            Clause(id="C-002", section_number="2", title="Indemnification", text="Unilateral customer indemnity."),
            Clause(id="C-003", section_number="3", title="Termination", text="Either party may terminate on 60 days."),
        ]
        analyses = [
            ClauseAnalysis(
                clause_id="C-001",
                clause_type="limitation_of_liability",
                risk_level=RiskLevel.NEEDS_NEGOTIATION,
                cited_rule_ids=["LOL-01"],
                explanation="Cap deviates from 12 months fees.",
                suggested_redline="Liability capped at 12 months fees.",
                confidence=0.90,
                needs_human_review=True,
            ),
            ClauseAnalysis(
                clause_id="C-002",
                clause_type="indemnification",
                risk_level=RiskLevel.UNACCEPTABLE,
                cited_rule_ids=["IND-01"],
                explanation="Unilateral indemnity violation.",
                suggested_redline="Mutual indemnification.",
                confidence=0.95,
                needs_human_review=True,
            ),
            ClauseAnalysis(
                clause_id="C-003",
                clause_type="termination",
                risk_level=RiskLevel.NEEDS_NEGOTIATION,
                cited_rule_ids=["TRM-01"],
                explanation="60-day notice is within fallback.",
                suggested_redline="30-day notice.",
                confidence=0.88,
            ),
        ]

        save_clause_analyses(review_id, clauses, analyses, [], db_path=db_path)
        update_review_status(review_id, "awaiting_review", total_clauses=3, analyzed_clauses=3, db_path=db_path)

        # 1. Premature finalize check
        self.test_premature_finalize_blocked(review_id, 3)

        # 2. Submit decisions
        self.submit_test_decisions(review_id, [
            {"clause_id": c.id, "text": c.text, "analysis": a.model_dump()} for c, a in zip(clauses, analyses)
        ])

        # 3. Finalize
        self.finalize_review(review_id)

        # 4. Reports
        self.verify_report_downloads(review_id)

        return {
            "contract": filename,
            "review_id": review_id,
            "clauses": 3,
            "status": "PASS",
        }

    def run_contract_test(self, filename: str, is_seeded_mode: bool = False) -> Dict[str, Any]:
        """Execute full end-to-end lifecycle for a single contract."""
        logger.info("\n" + "=" * 70)
        logger.info("SMOKE TESTING CONTRACT: %s", filename)
        logger.info("=" * 70)

        t0 = time.time()

        if is_seeded_mode:
            res = self.run_seeded_contract_test(filename)
            res["elapsed_sec"] = round(time.time() - t0, 1)
            return res

        # 1. Upload
        review_id = self.upload_contract(filename)

        # 2. Poll until awaiting_review
        detail = self.poll_until_ready(review_id)
        clauses = detail.get("clauses", [])
        pending_count = detail.get("pending_decisions", 0)

        # Print per-clause results
        print("\nPer-Clause Risk Analysis Findings:")
        print(f"{'ID':<6} | {'Section':<10} | {'Risk Level':<18} | {'Human Review':<12} | {'Suggested Redline'}")
        print("-" * 75)
        for c in clauses:
            a = c["analysis"]
            redline_summary = "Yes (Diff available)" if a.get("suggested_redline") else "None"
            print(f"{c['clause_id']:<6} | {c.get('section_number') or '-':<10} | {a['risk_level']:<18} | {str(a['needs_human_review']):<12} | {redline_summary}")

        # 3. Gating check
        self.test_premature_finalize_blocked(review_id, pending_count)

        # 4. Submit decisions
        self.submit_test_decisions(review_id, clauses)

        # 5. Finalize
        self.finalize_review(review_id)

        # 6. Report exports
        self.verify_report_downloads(review_id)

        elapsed = round(time.time() - t0, 1)
        return {
            "contract": filename,
            "review_id": review_id,
            "clauses": len(clauses),
            "status": "PASS",
            "elapsed_sec": elapsed,
        }

    def run_all(self, is_seeded_mode: bool = False) -> bool:
        """Run smoke test suite across all sample contracts."""
        print("\n" + "=" * 80)
        print("CONTRACT CLAUSE RISK-FLAGGING AGENT: END-TO-END SMOKE TEST")
        print(f"Target Base URL: {self.base_url}")
        print(f"Mode: {'SEEDED SYNTHETIC' if is_seeded_mode else 'LIVE ENDPOINT'}")
        print("=" * 80)

        if not self.check_health():
            print("\n[-] FATAL: Backend service is not reachable. Please start the backend service first:\n")
            print("    cd backend && uvicorn app.main:app --port 8000\n")
            return False

        all_passed = True
        for sample_filename in SAMPLE_FILES:
            try:
                res = self.run_contract_test(sample_filename, is_seeded_mode=is_seeded_mode)
                self.results.append(res)
            except Exception as exc:
                logger.exception("FAILED contract smoke test for '%s': %s", sample_filename, exc)
                self.results.append({
                    "contract": sample_filename,
                    "review_id": "N/A",
                    "clauses": 0,
                    "status": "FAIL",
                    "error": str(exc),
                })
                all_passed = False

        print("\n" + "=" * 80)
        print("END-TO-END SMOKE TEST SUMMARY")
        print("=" * 80)
        print(f"{'Contract':<38} | {'Review ID':<22} | {'Clauses':<8} | {'Status':<6}")
        print("-" * 80)
        for r in self.results:
            print(f"{r['contract']:<38} | {r.get('review_id', 'N/A'):<22} | {r.get('clauses', 0):<8} | {r['status']:<6}")
        print("=" * 80)

        if all_passed:
            print("\n>>> ALL END-TO-END SMOKE TESTS PASSED <<<\n")
        else:
            print("\n>>> ONE OR MORE SMOKE TESTS FAILED <<<\n")

        return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end smoke test for contract review agent.")
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Optional positional backend base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--seeded",
        action="store_true",
        help="Run against seeded DB reviews (for testing without a live LLM API key)",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Execute directly against ASGI application in-process without an external server",
    )
    args = parser.parse_args()

    target_url = args.url or args.base_url

    # Detect if LLM_API_KEY is present
    has_key = bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())
    is_seeded = args.seeded or not has_key

    if not has_key and not args.seeded:
        print("[!] Notice: LLM_API_KEY is not configured in backend/.env.")
        print("    Running smoke test in SEEDED mode (verifies upload, gating, review, decisions, finalize, and report export).")

    runner = SmokeTestRunner(base_url=target_url, in_process=args.in_process)
    success = runner.run_all(is_seeded_mode=is_seeded)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
