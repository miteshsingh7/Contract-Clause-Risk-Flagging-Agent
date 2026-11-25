#!/usr/bin/env python3
"""Evaluation runner comparing sample contract pipeline outputs against expected findings.

Supports resume functionality (--resume) for running within Free Tier daily quota limits.
Fails fast cleanly on quota exhaustion and saves progress per clause.

Usage:
    python3 backend/scripts/eval_samples.py [--resume] [--contract <filename>]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add backend directory to sys.path so app imports succeed
script_dir = Path(__file__).resolve().parent
backend_dir = script_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.graph.clause_graph import clause_analysis_graph, redline_node
from app.models.schemas import Clause, ClauseAnalysis, RiskLevel
from app.services.llm import DailyQuotaExceededError, get_llm_stats, reset_llm_stats
from app.services.parser import parse_document
from app.services.segmenter import segment_document
from app.services.vector_store import ingest_playbook

# Suppress noisy logs during eval output
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)


PROGRESS_FILE = Path(settings.LLM_CACHE_DIR) / "eval_progress.json"


def load_progress() -> Dict[str, Dict[str, Any]]:
    """Load cached evaluation progress if file exists."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_progress(progress: Dict[str, Dict[str, Any]]) -> None:
    """Save evaluation progress to disk."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def _extract_risk_str(val: Any) -> str:
    """Helper to extract risk level string from schema objects or dictionaries."""
    if hasattr(val, "risk_level"):
        rl = val.risk_level
        return rl.value if hasattr(rl, "value") else str(rl)
    if isinstance(val, dict):
        rl = val.get("risk_level", "")
        return rl.value if hasattr(rl, "value") else str(rl)
    return str(val)


def compute_dual_scores(
    actual_results: Dict[str, Dict[str, Any]],
    expected_findings: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Calculate match metrics against both original and revised benchmarks.

    Args:
        actual_results: Mapping of contract filename to mapping of clause index/key to analysis or dict.
        expected_findings: Mapping of contract filename to mapping of clause index/key to expected finding dict.

    Returns:
        Dict containing per_contract stats, overall stats, and details of revised clauses.
    """
    per_contract: Dict[str, Dict[str, Any]] = {}
    total_evaluated = 0
    total_orig_matches = 0
    total_revised_matches = 0
    revised_clauses: List[Dict[str, Any]] = []

    for contract_name, expected_clauses in expected_findings.items():
        if contract_name not in actual_results:
            continue
        contract_actual = actual_results[contract_name]
        c_evaluated = 0
        c_orig_matches = 0
        c_revised_matches = 0

        for key, exp_info in expected_clauses.items():
            if key not in contract_actual:
                continue

            c_evaluated += 1
            total_evaluated += 1

            act_risk = _extract_risk_str(contract_actual[key]).strip().lower()
            revised_exp = exp_info.get("expected_risk", "").strip().lower()
            orig_exp = exp_info.get("original_expected_risk", exp_info.get("expected_risk", "")).strip().lower()

            is_revised = act_risk == revised_exp
            is_orig = act_risk == orig_exp

            if is_revised:
                c_revised_matches += 1
                total_revised_matches += 1
            if is_orig:
                c_orig_matches += 1
                total_orig_matches += 1

            if "original_expected_risk" in exp_info:
                revised_clauses.append({
                    "contract": contract_name,
                    "clause_key": key,
                    "clause_type": exp_info.get("clause_type", "unknown"),
                    "original_expected_risk": exp_info.get("original_expected_risk"),
                    "revised_expected_risk": exp_info.get("expected_risk"),
                    "actual_risk": _extract_risk_str(contract_actual[key]),
                    "label_revision_note": exp_info.get("label_revision_note", ""),
                })

        orig_pct = (c_orig_matches / c_evaluated * 100.0) if c_evaluated > 0 else 0.0
        revised_pct = (c_revised_matches / c_evaluated * 100.0) if c_evaluated > 0 else 0.0
        per_contract[contract_name] = {
            "total_evaluated": c_evaluated,
            "original_matches": c_orig_matches,
            "original_pct": orig_pct,
            "revised_matches": c_revised_matches,
            "revised_pct": revised_pct,
        }

    overall_orig_pct = (total_orig_matches / total_evaluated * 100.0) if total_evaluated > 0 else 0.0
    overall_revised_pct = (total_revised_matches / total_evaluated * 100.0) if total_evaluated > 0 else 0.0

    return {
        "per_contract": per_contract,
        "overall": {
            "total_evaluated": total_evaluated,
            "original_matches": total_orig_matches,
            "original_pct": overall_orig_pct,
            "revised_matches": total_revised_matches,
            "revised_pct": overall_revised_pct,
        },
        "revised_clauses": revised_clauses,
    }


async def run_evaluation(
    resume: bool = False,
    target_contract: Optional[str] = None,
    no_redline: bool = False,
) -> None:
    """Run automated evaluation on sample contracts with quota tracking and resume support."""
    print("=" * 80)
    print("CONTRACT CLAUSE RISK EVALUATION RUNNER (Gemini Free Tier Quota-Aware)")
    print("Comparing LangGraph Pipeline Output Against Ground-Truth Benchmark")
    if no_redline:
        print("Mode: --no-redline (Skipping redlines; marking as 'pending' for non-Acceptable)")
    print("=" * 80)

    # Check for Gemini API key
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        print(
            "\n[!] Notice: LLM_API_KEY is not configured in backend/.env or environment.\n"
            "    Running evaluation requires a valid Gemini API key.\n"
        )
        sys.exit(1)

    samples_dir = backend_dir / "data" / "samples"
    expected_path = samples_dir / "expected_findings.json"

    if not expected_path.exists():
        print(f"Error: Expected findings file not found at '{expected_path}'", file=sys.stderr)
        sys.exit(1)

    with open(expected_path, "r", encoding="utf-8") as f:
        expected_data: Dict[str, Any] = json.load(f)

    # Ingest playbook into vector store
    print("Ensuring playbook vector store is updated...")
    await ingest_playbook()

    progress = load_progress() if resume else {}
    if resume and progress:
        cached_clause_count = sum(len(clauses) for clauses in progress.values())
        print(f"Resuming evaluation: Loaded {cached_clause_count} previously evaluated clauses from cache.")
    elif not resume and PROGRESS_FILE.exists():
        print("Starting fresh evaluation (ignoring previous eval_progress.json).")

    total_clauses_evaluated = 0
    total_matches = 0
    quota_exhausted = False

    for sample_filename, expected_clauses in expected_data.items():
        if target_contract and sample_filename != target_contract:
            continue

        sample_path = samples_dir / sample_filename
        if not sample_path.exists():
            print(f"Warning: Sample file '{sample_filename}' not found, skipping.")
            continue

        print("\n" + "=" * 80)
        print(f"EVALUATING: {sample_filename}")
        print("=" * 80)

        contract_progress = progress.setdefault(sample_filename, {})
        if resume and contract_progress:
            print(f"Resuming {sample_filename}: Loaded {len(contract_progress)} previously evaluated clauses from progress.")

        # Parse and segment contract
        doc = parse_document(sample_path)
        seg_result = await segment_document(doc)
        clauses = seg_result.clauses

        print(f"{'Sec':<4} | {'Clause Type':<23} | {'Expected Risk':<25} | {'Actual Risk':<18} | {'Status':<12} | {'Redline':<8}")
        print("-" * 96)

        contract_revised_matches = 0
        contract_orig_matches = 0
        contract_evaluated = 0
        flagged_clauses = []
        contract_start_time = time.time()
        initial_stats = get_llm_stats()

        for idx, clause in enumerate(clauses, 1):
            key = str(idx)
            expected_info = expected_clauses.get(key, {})
            expected_risk = expected_info.get("expected_risk", "Unknown")
            orig_expected_risk = expected_info.get("original_expected_risk", expected_risk)

            analysis: Optional[ClauseAnalysis] = None

            # Check if this clause was already evaluated and saved in progress
            if key in contract_progress:
                analysis_dict = contract_progress[key]
                analysis = ClauseAnalysis.model_validate(analysis_dict)

                # If running without --no-redline, fill in any pending redlines for non-Acceptable clauses
                if (
                    not no_redline
                    and analysis.risk_level != RiskLevel.ACCEPTABLE
                    and analysis.suggested_redline == "pending"
                ):
                    try:
                        redline_res = await redline_node({
                            "clause": clause,
                            "risk_level": analysis.risk_level,
                            "explanation": analysis.explanation,
                            "cited_rule_ids": analysis.cited_rule_ids,
                            "raise_quota_error": True,
                        })
                        analysis.suggested_redline = redline_res.get("suggested_redline")
                        contract_progress[key] = analysis.model_dump()
                        save_progress(progress)
                    except DailyQuotaExceededError as exc:
                        quota_exhausted = True
                        print(f"\n[!] Daily quota reached during redline generation for clause {idx}.")
                        print(f"    Error: {exc}")
                        print(f"    Progress saved to {PROGRESS_FILE}.")
                        print("    Rerun after the daily reset using: python3 backend/scripts/eval_samples.py --resume")
                        break
                    except Exception as exc:
                        msg = str(exc).lower()
                        if "per day" in msg or "generaterequestsperday" in msg or "429" in msg:
                            quota_exhausted = True
                            print(f"\n[!] Daily quota reached during redline generation for clause {idx}.")
                            print(f"    Error: {exc}")
                            print(f"    Progress saved to {PROGRESS_FILE}.")
                            print("    Rerun after the daily reset using: python3 backend/scripts/eval_samples.py --resume")
                            break
                        raise
            else:
                try:
                    result_state = await clause_analysis_graph.ainvoke({
                        "clause": clause,
                        "skip_redline": no_redline,
                    })
                    analysis = result_state.get("final_analysis")
                    if analysis is None:
                        s_redline = (
                            "pending"
                            if (no_redline and result_state.get("risk_level") != RiskLevel.ACCEPTABLE)
                            else result_state.get("suggested_redline")
                        )
                        analysis = ClauseAnalysis(
                            clause_id=clause.id,
                            clause_type=result_state.get("clause_type", "other"),
                            risk_level=result_state.get("risk_level", RiskLevel.NEEDS_NEGOTIATION),
                            cited_rule_ids=result_state.get("cited_rule_ids", []),
                            explanation=result_state.get("explanation", "Analysis completed."),
                            suggested_redline=s_redline,
                            confidence=result_state.get("analysis_confidence", 0.5),
                            needs_human_review=result_state.get("needs_human_review", False),
                            review_reason=result_state.get("review_reason"),
                        )

                    # Save immediately to progress
                    contract_progress[key] = analysis.model_dump()
                    save_progress(progress)

                except DailyQuotaExceededError as exc:
                    quota_exhausted = True
                    print(f"\n[!] Daily quota reached after {total_clauses_evaluated + contract_evaluated} clauses.")
                    print(f"    Error: {exc}")
                    print(f"    Progress saved to {PROGRESS_FILE}.")
                    print("    Rerun after the daily reset using: python3 backend/scripts/eval_samples.py --resume")
                    break
                except Exception as exc:
                    msg = str(exc).lower()
                    if "per day" in msg or "generaterequestsperday" in msg or "429" in msg:
                        quota_exhausted = True
                        print(f"\n[!] Daily quota reached after {total_clauses_evaluated + contract_evaluated} clauses.")
                        print(f"    Error: {exc}")
                        print(f"    Progress saved to {PROGRESS_FILE}.")
                        print("    Rerun after the daily reset using: python3 backend/scripts/eval_samples.py --resume")
                        break
                    raise

            actual_risk = analysis.risk_level.value
            is_revised_match = actual_risk.lower() == expected_risk.lower()
            is_orig_match = actual_risk.lower() == orig_expected_risk.lower()
            if is_revised_match:
                contract_revised_matches += 1
                total_matches += 1
            if is_orig_match:
                contract_orig_matches += 1
            contract_evaluated += 1

            if analysis.needs_human_review and analysis.review_reason:
                flagged_clauses.append((idx, analysis.clause_type, analysis.review_reason))

            if "original_expected_risk" in expected_info:
                exp_display = f"{expected_risk} (orig: {orig_expected_risk})"
                status_str = f"{'MATCH' if is_revised_match else 'DIFF'} (orig:{'M' if is_orig_match else 'D'})"
            else:
                exp_display = expected_risk
                status_str = "MATCH" if is_revised_match else "DIFF"

            redline_status = (
                "Pending"
                if analysis.suggested_redline == "pending"
                else ("Yes" if analysis.suggested_redline else "None")
            )
            print(
                f"{idx:<4} | {analysis.clause_type:<23} | {exp_display:<25} | "
                f"{actual_risk:<18} | {status_str:<12} | {redline_status:<8}"
            )

        total_clauses_evaluated += contract_evaluated
        elapsed = time.time() - contract_start_time
        final_stats = get_llm_stats()

        contract_live_comp = final_stats["live_completion_calls"] - initial_stats["live_completion_calls"]
        contract_cached_comp = final_stats["cached_completion_calls"] - initial_stats["cached_completion_calls"]
        contract_live_embed = final_stats["live_embedding_calls"] - initial_stats["live_embedding_calls"]
        contract_retries = final_stats["retries_count"] - initial_stats["retries_count"]
        contract_malformed = final_stats["malformed_count"] - initial_stats["malformed_count"]

        rev_pct = (contract_revised_matches / contract_evaluated * 100.0) if contract_evaluated > 0 else 0.0
        orig_pct = (contract_orig_matches / contract_evaluated * 100.0) if contract_evaluated > 0 else 0.0
        print("-" * 80)
        print(
            f"Contract Scores: Revised: {contract_revised_matches}/{contract_evaluated} ({rev_pct:.1f}%) | "
            f"Original: {contract_orig_matches}/{contract_evaluated} ({orig_pct:.1f}%)\n"
            f"Elapsed: {elapsed:.1f}s | LLM Calls: {contract_live_comp} live, {contract_cached_comp} cached | "
            f"Embeddings: {contract_live_embed} live | Retries: {contract_retries} | Malformed: {contract_malformed}"
        )
        if flagged_clauses:
            print("Flagged / Fallback Clauses:")
            for c_idx, c_type, c_reason in flagged_clauses:
                print(f"  - Clause {c_idx} ({c_type}): {c_reason}")

        if quota_exhausted:
            break

    dual_summary = compute_dual_scores(progress, expected_data)
    overall = dual_summary["overall"]

    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY: DUAL BENCHMARK SCORES")
    print("=" * 80)
    print("Per-Contract Breakdown:")
    for c_name, c_scores in dual_summary["per_contract"].items():
        print(
            f"  * {c_name}:\n"
            f"      Revised Benchmark:  {c_scores['revised_matches']}/{c_scores['total_evaluated']} ({c_scores['revised_pct']:.1f}%)\n"
            f"      Original Benchmark: {c_scores['original_matches']}/{c_scores['total_evaluated']} ({c_scores['original_pct']:.1f}%)"
        )

    print(
        f"\nOverall Match:\n"
        f"  - Revised Benchmark:  {overall['revised_matches']}/{overall['total_evaluated']} ({overall['revised_pct']:.1f}% match)\n"
        f"  - Original Benchmark: {overall['original_matches']}/{overall['total_evaluated']} ({overall['original_pct']:.1f}% match)"
    )

    if dual_summary["revised_clauses"]:
        print(f"\nRevised Benchmark Clauses ({len(dual_summary['revised_clauses'])} corrections):")
        for idx, rc in enumerate(dual_summary["revised_clauses"], 1):
            print(
                f"  {idx}. {rc['contract']} - Clause {rc['clause_key']} ({rc['clause_type']}):\n"
                f"     Original: {rc['original_expected_risk']} -> Revised: {rc['revised_expected_risk']}\n"
                f"     Actual Model Output: {rc['actual_risk']}\n"
                f"     Reason: {rc['label_revision_note']}"
            )

    all_stats = get_llm_stats()
    print("-" * 80)
    print(
        f"Total LLM Completions: {all_stats['live_completion_calls']} live, {all_stats['cached_completion_calls']} cached | "
        f"Embeddings: {all_stats['live_embedding_calls']} live, {all_stats['cached_embedding_calls']} cached"
    )
    if quota_exhausted:
        print("[!] Evaluation paused due to Free Tier daily quota limit. Run with --resume when quota resets.")
    else:
        print("[✓] Evaluation completed for all evaluated contracts.")
    print("=" * 80)
    await asyncio.sleep(0.2)


def main() -> None:
    """Entry point parsing CLI flags."""
    parser = argparse.ArgumentParser(description="Evaluate sample contracts against expected risk findings.")
    parser.add_argument("--resume", action="store_true", help="Resume from cached eval progress.")
    parser.add_argument("--contract", type=str, default=None, help="Evaluate a specific sample contract filename.")
    parser.add_argument(
        "--no-redline",
        action="store_true",
        help="Skip redline generation and record redline as 'pending'.",
    )
    args = parser.parse_args()

    asyncio.run(
        run_evaluation(
            resume=args.resume,
            target_contract=args.contract,
            no_redline=args.no_redline,
        )
    )


if __name__ == "__main__":
    main()
