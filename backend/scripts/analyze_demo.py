#!/usr/bin/env python3
"""CLI demonstration tool for running the full contract analysis pipeline.

Usage:
    python3 backend/scripts/analyze_demo.py <path_to_contract_docx_or_pdf>

Example:
    python3 backend/scripts/analyze_demo.py backend/data/samples/sample_contract_compliant.docx
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports succeed
script_dir = Path(__file__).resolve().parent
backend_dir = script_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.graph.contract_graph import analyze_contract
from app.services.vector_store import ingest_playbook


async def run_analysis_demo(file_path: str) -> None:
    """Run full contract analysis pipeline on a target document."""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: Contract file not found at '{file_path}'", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print("CONTRACT CLAUSE RISK-FLAGGING AND REDLINE AGENT (DEMO)")
    print(f"Document: {path.name}")
    print(f"LLM Provider: {settings.LLM_PROVIDER} | Model: {settings.LLM_MODEL}")
    print("=" * 80)

    # Check for Gemini API key
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        print(
            "\n[!] Notice: LLM_API_KEY is not configured in backend/.env or environment.\n"
            "    Live contract analysis requires a valid Gemini API key.\n"
            "    Please configure LLM_API_KEY in backend/.env to run live analysis.\n\n"
            "    Example:\n"
            "      LLM_API_KEY=AIzaSy...\n"
        )
        sys.exit(0)

    # Ensure vector store is ingested
    print("Verifying playbook vector store index...")
    try:
        await ingest_playbook()
    except Exception as exc:
        print(f"Warning during vector store setup: {exc}", file=sys.stderr)

    print("Executing full LangGraph pipeline (parse -> segment -> classify -> retrieve -> analyze -> redline -> ground)...")
    try:
        result = await analyze_contract(path)
    except Exception as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Print Summary Metrics
    print("\n" + "=" * 80)
    print("CONTRACT ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"Total Substantive Clauses Evaluated: {result.total_clauses}")
    print(f"  - Acceptable:          {result.acceptable_count}")
    print(f"  - Needs Negotiation:   {result.needs_negotiation_count}")
    print(f"  - Unacceptable:        {result.unacceptable_count}")
    print(f"  - Needs Human Review:  {result.needs_human_review_count}")

    if result.missing_clause_types:
        print("\nMissing Playbook Clause Types (Informational):")
        for m in result.missing_clause_types:
            print(f"  * {m}")

    print("\n" + "-" * 80)
    print("PER-CLAUSE FINDINGS")
    print("-" * 80)

    for idx, analysis in enumerate(result.analyses, 1):
        rule_str = ", ".join(analysis.cited_rule_ids) if analysis.cited_rule_ids else "None"
        review_flag = " [NEEDS HUMAN REVIEW]" if analysis.needs_human_review else ""

        print(f"[{analysis.clause_id}] Section: {idx:<2} | Type: {analysis.clause_type} | Risk: {analysis.risk_level.value}{review_flag}")
        print(f"  Cited Rules: {rule_str}")
        print(f"  Confidence:  {analysis.confidence:.2f}")
        print(f"  Explanation: {analysis.explanation}")
        if analysis.needs_human_review and analysis.review_reason:
            print(f"  Review Note: {analysis.review_reason}")

        if analysis.suggested_redline:
            snippet = analysis.suggested_redline[:150].replace("\n", " ")
            ellipsis_str = "..." if len(analysis.suggested_redline) > 150 else ""
            print(f"  Redline:     {snippet}{ellipsis_str}")
        else:
            print("  Redline:     [None - Clause is Acceptable]")
        print()

    print("=" * 80)
    print("LEGAL ADVISORY NOTICE:")
    print(result.disclaimer)
    print("=" * 80)


def main() -> None:
    """Parse CLI arguments and run demo."""
    parser = argparse.ArgumentParser(
        description="Demo CLI for contract clause risk-flagging and redline suggestions."
    )
    parser.add_argument(
        "file_path",
        type=str,
        help="Path to contract .docx or .pdf file",
    )
    args = parser.parse_args()
    asyncio.run(run_analysis_demo(args.file_path))


if __name__ == "__main__":
    main()
