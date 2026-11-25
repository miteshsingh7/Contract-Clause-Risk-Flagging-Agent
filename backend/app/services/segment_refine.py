"""LLM refinement pass for contract clause segmentation boundaries.

Provides a second-pass boundary review using the structured LLM interface.
Validates whether any clause was inadvertently split in half or if two separate
clauses were merged. Returns ONLY boundary corrections (merges/splits), never rewritten text.

Guarantees full text preservation: if any characters/words are lost or altered,
or if the LLM call fails, it silently falls back to the heuristic result.
"""

import copy
import logging
import re
from typing import List, Optional

from app.core.config import settings
from app.models.schemas import Clause, MergeCorrection, RefinementPlan, SplitCorrection
from app.services.llm import generate_structured_json

logger = logging.getLogger(__name__)


def _normalize_text_for_verification(clauses: List[Clause]) -> str:
    """Extract and normalize all non-whitespace text from a list of clauses for strict verification."""
    combined = "".join(c.text for c in clauses)
    # Remove all whitespace characters to verify character-for-character textual preservation
    return re.sub(r"\s+", "", combined)


def _apply_merges(clauses: List[Clause], merges: List[MergeCorrection]) -> List[Clause]:
    """Merge specified consecutive clauses while strictly preserving verbatim text."""
    if not merges:
        return clauses

    # Create mapping of clause id to copy of clause
    clause_map = {c.id: copy.deepcopy(c) for c in clauses}
    merged_ids_set = set()

    for m in merges:
        if len(m.clause_ids) < 2:
            continue
        # Check all IDs exist
        if not all(cid in clause_map for cid in m.clause_ids):
            logger.warning("Merge skipped: one or more clause IDs not found: %s", m.clause_ids)
            continue

        primary_id = m.clause_ids[0]
        # Combine text of all clauses to be merged
        combined_texts = [clause_map[cid].text for cid in m.clause_ids]
        clause_map[primary_id].text = "\n\n".join(combined_texts)

        # Mark subsequent clauses as merged
        for cid in m.clause_ids[1:]:
            merged_ids_set.add(cid)

    # Return filtered list preserving original order
    return [clause_map[c.id] for c in clauses if c.id not in merged_ids_set]


def _apply_splits(clauses: List[Clause], splits: List[SplitCorrection]) -> List[Clause]:
    """Split specified clauses at exact substrings while preserving verbatim text."""
    if not splits:
        return clauses

    split_map = {s.clause_id: s for s in splits}
    result: List[Clause] = []

    for clause in clauses:
        if clause.id not in split_map:
            result.append(copy.deepcopy(clause))
            continue

        split_instr = split_map[clause.id]
        delimiter = split_instr.split_after_text.strip()

        if not delimiter or delimiter not in clause.text:
            logger.warning(
                "Split skipped for %s: split_after_text '%s' not found verbatim in clause text.",
                clause.id,
                delimiter,
            )
            result.append(copy.deepcopy(clause))
            continue

        # Split after the exact delimiter
        idx = clause.text.find(delimiter) + len(delimiter)
        part1 = clause.text[:idx].strip()
        part2 = clause.text[idx:].strip()

        if not part1 or not part2:
            # Degenerate split, keep original
            result.append(copy.deepcopy(clause))
            continue

        c1 = copy.deepcopy(clause)
        c1.text = part1
        result.append(c1)

        # Create new clause for second part
        new_clause_id = f"{clause.id}_split"
        new_clause = Clause(
            id=new_clause_id,
            section_number=clause.section_number,
            title=split_instr.new_clause_title or f"{clause.title or 'Clause'} (Part 2)",
            text=part2,
            clause_type=None,
        )
        result.append(new_clause)

    return result


async def refine_clauses_with_llm(
    clauses: List[Clause],
    enable_refinement: Optional[bool] = None,
) -> List[Clause]:
    """Review and refine clause boundaries using an LLM.

    Args:
        clauses: Initial list of heuristically segmented clauses.
        enable_refinement: Explicit override flag. If None, checks settings.ENABLE_LLM_SEGMENT_REFINEMENT.

    Returns:
        Refined list of clauses if corrections were valid and verified;
        otherwise, returns the original heuristic clauses.
    """
    should_run = (
        enable_refinement
        if enable_refinement is not None
        else settings.ENABLE_LLM_SEGMENT_REFINEMENT
    )

    if not should_run or len(clauses) == 0:
        return clauses

    # Capture original normalized text for strict verification before any alterations
    original_norm = _normalize_text_for_verification(clauses)

    # Build prompt representation of current clauses
    clauses_summary = []
    for c in clauses:
        snippet = c.text[:150].replace("\n", " ") + ("..." if len(c.text) > 150 else "")
        clauses_summary.append(
            f"ID: {c.id} | Section: {c.section_number or 'N/A'} | Title: {c.title or 'N/A'}\n"
            f"Preview: {snippet}"
        )
    prompt_payload = "\n\n".join(clauses_summary)

    prompt = (
        "You are an expert contract segmentation specialist. Review the following segmented clauses:\n\n"
        f"{prompt_payload}\n\n"
        "Evaluate whether:\n"
        "1. Any single substantive clause was accidentally split into two separate entries (merge needed).\n"
        "2. Two distinct substantive clauses were accidentally merged into one (split needed).\n\n"
        "Rules:\n"
        "- Sub-clauses (e.g. 1.1, 1.2) MUST stay inside their parent top-level clause.\n"
        "- DO NOT rewrite, paraphrase, or edit any text.\n"
        "- If splits are needed, split_after_text must be an EXACT verbatim substring from the clause text.\n"
        "- If the boundaries are already correct, return has_corrections=False."
    )

    system_instruction = (
        "You are a legal contract structure analyzer. Analyze clause boundaries and output "
        "only boundary merge/split instructions in structured JSON conforming to the schema."
    )

    try:
        response_dict = await generate_structured_json(
            prompt=prompt,
            system_instruction=system_instruction,
            response_schema=RefinementPlan,
        )
        plan = RefinementPlan.model_validate(response_dict)
    except Exception as exc:
        logger.warning("LLM segment refinement failed or was unavailable: %s. Using heuristic result.", exc)
        return clauses

    if not plan.has_corrections or (not plan.merges and not plan.splits):
        logger.debug("LLM refinement confirmed heuristic boundaries with no changes needed.")
        return clauses

    # Deep copy original clauses before applying modifications
    working_clauses = [copy.deepcopy(c) for c in clauses]

    try:
        # Apply merges first, then splits
        if plan.merges:
            working_clauses = _apply_merges(working_clauses, plan.merges)
        if plan.splits:
            working_clauses = _apply_splits(working_clauses, plan.splits)

        # Re-index clause IDs to maintain clean sequential order (e.g. C-001, C-002...)
        for idx, cl in enumerate(working_clauses, 1):
            cl.id = f"C-{idx:03d}"

        # Strict text verification: Ensure no words or non-whitespace characters were altered or lost
        refined_norm = _normalize_text_for_verification(working_clauses)

        if original_norm != refined_norm:
            logger.warning(
                "LLM refinement failed text preservation check (length before: %d, length after: %d). "
                "Silently falling back to heuristic segmentation.",
                len(original_norm),
                len(refined_norm),
            )
            return clauses

        logger.info(
            "LLM refinement successfully applied %d merges and %d splits.",
            len(plan.merges),
            len(plan.splits),
        )
        return working_clauses

    except Exception as exc:
        logger.warning(
            "Unexpected error while applying refinement plan: %s. Falling back to heuristic result.",
            exc,
        )
        return clauses
