#!/usr/bin/env python3
"""CLI demonstration tool for playbook ingestion and semantic vector retrieval.

Usage:
    python3 backend/scripts/playbook_demo.py "<clause_text>" [--clause-type <type>] [--top-k <k>]

Example:
    python3 backend/scripts/playbook_demo.py "Total liability shall in no event exceed fees paid in prior 12 months" --clause-type limitation_of_liability
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
from app.services.vector_store import ingest_playbook, retrieve_rules


async def run_playbook_demo(
    clause_text: str,
    clause_type: str = None,
    top_k: int = 3,
    rebuild: bool = False,
) -> None:
    """Run vector store ingestion and semantic query retrieval."""
    print("=" * 80)
    print("PLAYBOOK VECTOR RETRIEVAL DEMO")
    print(f"Provider: {settings.LLM_PROVIDER} | Embedding Model: {settings.EMBEDDING_MODEL}")
    print(f"Chroma Storage: {settings.CHROMA_PATH}")
    print("=" * 80)

    # Check whether LLM_API_KEY is configured
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        print(
            "\n[!] Notice: LLM_API_KEY is not configured in backend/.env or environment.\n"
            "    Live semantic vector retrieval requires a valid Gemini API key.\n"
            "    Please configure LLM_API_KEY in backend/.env to run live vector queries.\n\n"
            "    Example:\n"
            "      LLM_API_KEY=AIzaSy...\n"
        )
        sys.exit(0)

    # Ingest / update playbook vector store
    print("\nEnsuring playbook rules are indexed in ChromaDB...")
    try:
        count = await ingest_playbook(rebuild=rebuild)
        print(f"Indexed {count} playbook rules into collection '{settings.PLAYBOOK_COLLECTION_NAME}'.")
    except Exception as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "-" * 80)
    print(f"QUERY CLAUSE: {clause_text}")
    if clause_type:
        print(f"FILTER CLAUSE TYPE: {clause_type}")
    print(f"TOP K: {top_k}")
    print("-" * 80)

    # Query vector store
    try:
        results = await retrieve_rules(
            clause_text=clause_text,
            clause_type=clause_type,
            top_k=top_k,
        )
    except Exception as exc:
        print(f"Retrieval failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print("\nNo matching playbook rules found for this query.")
        return

    print(f"\nRetrieved {len(results)} matching rules:\n")
    for rank, (rule, score) in enumerate(results, 1):
        print(f"[{rank}] Score: {score:.4f} | Rule ID: {rule.rule_id} | Type: {rule.clause_type}")
        print(f"    Title: {rule.title}")
        print(f"    Standard Position: {rule.standard_position[:100]}...")
        print(f"    Acceptable Fallback: {rule.acceptable_fallback[:100]}...")
        if rule.unacceptable_triggers:
            triggers = ", ".join(rule.unacceptable_triggers[:3])
            print(f"    Triggers: {triggers}...")
        print()

    print("=" * 80)
    print("DONE: Retrieval complete.")
    print("=" * 80)


def main() -> None:
    """Parse CLI arguments and run demo."""
    parser = argparse.ArgumentParser(
        description="Demo CLI for playbook vector store ingestion and retrieval."
    )
    parser.add_argument(
        "clause_text",
        type=str,
        help="Contract clause text to match against the corporate playbook",
    )
    parser.add_argument(
        "--clause-type",
        "-t",
        type=str,
        default=None,
        help="Optional clause type to filter search (e.g. 'limitation_of_liability')",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=3,
        help="Number of top matching rules to retrieve (default: 3)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force complete rebuild of the vector collection before searching",
    )
    args = parser.parse_args()

    asyncio.run(
        run_playbook_demo(
            clause_text=args.clause_text,
            clause_type=args.clause_type,
            top_k=args.top_k,
            rebuild=args.rebuild,
        )
    )


if __name__ == "__main__":
    main()
