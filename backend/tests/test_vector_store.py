"""Tests for ChromaDB vector store ingestion and semantic retrieval.

All tests use a deterministic mocked embedding function and temporary isolated
ChromaDB directories to ensure NO real external API calls are made.
"""

import hashlib
import math
import tempfile
from pathlib import Path
from typing import List, Optional, Union
from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import PlaybookRule
from app.services.playbook import load_playbook
from app.services.vector_store import (
    format_rule_document,
    get_playbook_collection,
    ingest_playbook,
    init_vector_store,
    retrieve_rules,
)


def fake_generate_embedding(
    text: Union[str, List[str]],
    model: Optional[str] = None,
) -> Union[List[float], List[List[float]]]:
    """Deterministic mock embedding function generating normalized 64-dim float vectors."""
    is_single = isinstance(text, str)
    items = [text] if is_single else text
    vectors: List[List[float]] = []

    for t in items:
        # Use SHA-256 hash of normalized text to create deterministic floats
        h = hashlib.sha256(t.lower().strip().encode("utf-8")).digest()
        # Create 64 values from 32 bytes (repeated)
        raw_values = [float(b) for b in (h * 2)[:64]]
        magnitude = math.sqrt(sum(val * val for val in raw_values)) or 1.0
        normalized = [round(val / magnitude, 5) for val in raw_values]
        vectors.append(normalized)

    if is_single:
        return vectors[0]
    return vectors


@pytest.fixture(autouse=True)
def mock_embedding_service():
    """Patch generate_embedding across all vector store tests."""
    with patch(
        "app.services.vector_store.generate_embedding",
        new=AsyncMock(side_effect=fake_generate_embedding),
    ) as mocked_fn:
        yield mocked_fn


def test_format_rule_document() -> None:
    """Verify semantic text formatting of a PlaybookRule."""
    rule = PlaybookRule(
        rule_id="LOL-01",
        clause_type="limitation_of_liability",
        title="Aggregate Liability Cap",
        standard_position="Cap at 12 months fees.",
        acceptable_fallback="Cap at 2x 12 months fees.",
        unacceptable_triggers=["unlimited liability", "no cap"],
        preferred_language="Preferred model text.",
        rationale="Prevents catastrophic financial loss.",
    )

    doc_text = format_rule_document(rule)
    assert "Clause Type: limitation_of_liability" in doc_text
    assert "Title: Aggregate Liability Cap" in doc_text
    assert "Standard Position: Cap at 12 months fees." in doc_text
    assert "Acceptable Fallback: Cap at 2x 12 months fees." in doc_text
    assert "Unacceptable Triggers: unlimited liability, no cap" in doc_text


@pytest.mark.anyio
async def test_idempotent_ingestion() -> None:
    """Ensure that running playbook ingestion multiple times upserts without duplicating."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        rules = load_playbook(reload=True)
        assert len(rules) == 13

        # Run 1: initial ingestion
        count_1 = await ingest_playbook(rules=rules, chroma_path=tmp_chroma)
        assert count_1 == 13

        # Run 2: re-ingest same rules -> must remain exactly 13
        count_2 = await ingest_playbook(rules=rules, chroma_path=tmp_chroma)
        assert count_2 == 13

        # Verify underlying collection count directly
        collection = get_playbook_collection(chroma_path=tmp_chroma)
        assert collection.count() == 13


@pytest.mark.anyio
async def test_rebuild_ingestion() -> None:
    """Ensure rebuild=True clears and re-indexes collection."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        rules = load_playbook(reload=True)

        # Ingest initially
        await ingest_playbook(rules=rules, chroma_path=tmp_chroma)

        # Ingest with rebuild=True
        count = await ingest_playbook(rules=rules, rebuild=True, chroma_path=tmp_chroma)
        assert count == 13

        collection = get_playbook_collection(chroma_path=tmp_chroma)
        assert collection.count() == 13


@pytest.mark.anyio
async def test_unfiltered_retrieval() -> None:
    """Test semantic retrieval across all rules without clause_type filtering."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        await ingest_playbook(chroma_path=tmp_chroma)

        query = "Neither party shall be liable for aggregate damages exceeding twelve months fees paid."
        results = await retrieve_rules(clause_text=query, top_k=3, chroma_path=tmp_chroma)

        assert len(results) == 3
        for rule, score in results:
            assert isinstance(rule, PlaybookRule)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0


@pytest.mark.anyio
async def test_filtered_retrieval_by_clause_type() -> None:
    """Test retrieval filtered by clause_type."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        await ingest_playbook(chroma_path=tmp_chroma)

        query = "Either party may terminate without cause upon thirty days written notice."
        results = await retrieve_rules(
            clause_text=query,
            clause_type="termination",
            top_k=5,
            chroma_path=tmp_chroma,
        )

        assert len(results) >= 1
        # All returned rules must match the specified clause type
        for rule, score in results:
            assert rule.clause_type == "termination"
            assert rule.rule_id.startswith("TRM")
            assert 0.0 <= score <= 1.0


@pytest.mark.anyio
async def test_empty_results_handling() -> None:
    """Ensure graceful handling when no results match or collection is empty."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        # Case 1: Search on empty collection before ingestion
        empty_res_1 = await retrieve_rules(
            clause_text="Some contract clause",
            chroma_path=tmp_chroma,
        )
        assert empty_res_1 == []

        # Ingest rules
        await ingest_playbook(chroma_path=tmp_chroma)

        # Case 2: Filter by a clause type that does not exist in the playbook
        empty_res_2 = await retrieve_rules(
            clause_text="Some clause text",
            clause_type="non_existent_category",
            chroma_path=tmp_chroma,
        )
        assert empty_res_2 == []

        # Case 3: Empty query text
        empty_res_3 = await retrieve_rules(clause_text="", chroma_path=tmp_chroma)
        assert empty_res_3 == []


@pytest.mark.anyio
async def test_startup_auto_ingestion() -> None:
    """Test init_vector_store auto-ingestion on empty collection."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        with patch("app.core.config.settings.CHROMA_PATH", tmp_chroma):
            # Initially empty collection
            await init_vector_store()
            collection = get_playbook_collection(chroma_path=tmp_chroma)
            assert collection.count() == 13
