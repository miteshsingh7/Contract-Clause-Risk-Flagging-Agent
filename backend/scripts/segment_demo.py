#!/usr/bin/env python3
"""CLI demonstration tool for contract parsing and clause segmentation.

Usage:
    python3 backend/scripts/segment_demo.py <path_to_docx_or_pdf> [--refine]

Example:
    python3 backend/scripts/segment_demo.py backend/data/samples/sample_contract_compliant.docx
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

from app.services.parser import parse_document
from app.services.segmenter import segment_document


async def run_segmentation_demo(file_path: str, enable_refine: bool = False) -> None:
    """Parse and segment a contract file and display the results."""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found at '{file_path}'", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print(f"CONTRACT SEGMENTATION DEMO: {path.name}")
    print(f"Path: {path.resolve()}")
    print(f"LLM Refinement Pass: {'ENABLED' if enable_refine else 'DISABLED'}")
    print("=" * 80)

    try:
        parsed_doc = parse_document(path)
    except Exception as exc:
        print(f"Parsing failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Parsed {parsed_doc.total_paragraphs} paragraphs from {parsed_doc.file_type.upper()} document.")

    try:
        result = await segment_document(parsed_doc, enable_llm_refinement=enable_refine)
    except Exception as exc:
        print(f"Segmentation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # 1. Preamble
    if result.preamble:
        print("\n" + "-" * 80)
        print("PREAMBLE / RECITAL BLOCK (Marked as Non-Substantive)")
        print("-" * 80)
        preamble_snippet = result.preamble[:200].replace("\n", " ")
        print(preamble_snippet + ("..." if len(result.preamble) > 200 else ""))

    # 2. Definitions
    if result.definitions:
        print("\n" + "-" * 80)
        print("DEFINITIONS SECTION (Kept Separate from Substantive Clauses)")
        print("-" * 80)
        print(f"Title: {result.definitions.title}")
        def_snippet = result.definitions.text[:150].replace("\n", " ")
        print(f"Text: {def_snippet}...")

    # 3. Substantive Clauses
    print("\n" + "-" * 80)
    print(f"SUBSTANTIVE CLAUSES EXTRACTED ({len(result.clauses)} total)")
    print("-" * 80)

    for clause in result.clauses:
        sec = clause.section_number or "N/A"
        title = clause.title or "Untitled"
        # First 100 characters of text
        snippet = clause.text[:100].replace("\n", " ")
        ellipsis_str = "..." if len(clause.text) > 100 else ""
        print(f"[{clause.id}] Section: {sec:<4} | Title: {title}")
        print(f"       Text: {snippet}{ellipsis_str}")
        print()

    # 4. Signature Block
    if result.signature_block:
        print("-" * 80)
        print("SIGNATURE BLOCK (Marked as Non-Substantive)")
        print("-" * 80)
        sig_snippet = result.signature_block[:150].replace("\n", " ")
        print(sig_snippet + ("..." if len(result.signature_block) > 150 else ""))

    print("=" * 80)
    print(f"DONE: Successfully segmented {len(result.clauses)} substantive clauses.")
    print("=" * 80)


def main() -> None:
    """Parse CLI arguments and run demo."""
    parser = argparse.ArgumentParser(
        description="Demo CLI for contract clause segmentation."
    )
    parser.add_argument(
        "file_path",
        type=str,
        help="Path to contract .docx or text-based .pdf",
    )
    parser.add_argument(
        "--refine",
        action="store_true",
        help="Enable LLM refinement pass for boundary adjustments",
    )
    args = parser.parse_args()
    asyncio.run(run_segmentation_demo(args.file_path, enable_refine=args.refine))


if __name__ == "__main__":
    main()
