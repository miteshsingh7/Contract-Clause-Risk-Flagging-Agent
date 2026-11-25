"""Word-level diff helper using Python's standard library difflib.

Preserves exact whitespace and ordering such that:
- Joined (equal + delete) segments reconstruct original_text verbatim.
- Joined (equal + insert) segments reconstruct revised_text verbatim.
"""

import difflib
import re
from typing import Any, Dict, List

from app.models.schemas import DiffSegment, DiffType


def compute_word_diff(original_text: str, revised_text: str) -> List[Dict[str, str]]:
    """Compute word-level diff segments between original and revised text.

    Args:
        original_text: Verbatim original text.
        revised_text: Proposed or revised text.

    Returns:
        Ordered list of dicts with keys 'type' ('equal'|'insert'|'delete') and 'text'.
    """
    if original_text == revised_text:
        if not original_text:
            return []
        return [{"type": DiffType.EQUAL.value, "text": original_text}]

    # Tokenize preserving all whitespace and non-whitespace tokens
    tokens_orig = re.findall(r"\S+|\s+", original_text)
    tokens_rev = re.findall(r"\S+|\s+", revised_text)

    matcher = difflib.SequenceMatcher(None, tokens_orig, tokens_rev)
    segments: List[Dict[str, str]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segments.append({
                "type": DiffType.EQUAL.value,
                "text": "".join(tokens_orig[i1:i2]),
            })
        elif tag == "delete":
            segments.append({
                "type": DiffType.DELETE.value,
                "text": "".join(tokens_orig[i1:i2]),
            })
        elif tag == "insert":
            segments.append({
                "type": DiffType.INSERT.value,
                "text": "".join(tokens_rev[j1:j2]),
            })
        elif tag == "replace":
            # Emit deletion followed by insertion
            segments.append({
                "type": DiffType.DELETE.value,
                "text": "".join(tokens_orig[i1:i2]),
            })
            segments.append({
                "type": DiffType.INSERT.value,
                "text": "".join(tokens_rev[j1:j2]),
            })

    return segments


def reconstruct_original(segments: List[Dict[str, Any]]) -> str:
    """Reconstruct original text from diff segments (equal + delete)."""
    return "".join(
        s["text"] for s in segments
        if s.get("type") in (DiffType.EQUAL.value, DiffType.DELETE.value, "equal", "delete")
    )


def reconstruct_revised(segments: List[Dict[str, Any]]) -> str:
    """Reconstruct revised text from diff segments (equal + insert)."""
    return "".join(
        s["text"] for s in segments
        if s.get("type") in (DiffType.EQUAL.value, DiffType.INSERT.value, "equal", "insert")
    )
