"""Tests for the /playbook API endpoints."""

import tempfile
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.vector_store import ingest_playbook
from tests.test_vector_store import fake_generate_embedding


@pytest.fixture
def api_client():
    """Create FastAPI test client."""
    return TestClient(app)


def test_api_get_all_rules(api_client: TestClient) -> None:
    """Ensure GET /playbook/rules returns all 13 playbook rules."""
    response = api_client.get("/playbook/rules")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 13
    rule_ids = {r["rule_id"] for r in data}
    assert "LOL-01" in rule_ids
    assert "IND-01" in rule_ids


def test_api_get_rules_filtered(api_client: TestClient) -> None:
    """Ensure GET /playbook/rules?clause_type=termination filters correctly."""
    response = api_client.get("/playbook/rules?clause_type=termination")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(r["clause_type"] == "termination" for r in data)


def test_api_get_rule_by_id_valid(api_client: TestClient) -> None:
    """Ensure GET /playbook/rules/{rule_id} returns rule for valid ID."""
    response = api_client.get("/playbook/rules/LOL-01")
    assert response.status_code == 200
    data = response.json()
    assert data["rule_id"] == "LOL-01"
    assert data["clause_type"] == "limitation_of_liability"
    assert "Aggregate Liability Cap" in data["title"]


def test_api_get_rule_by_id_not_found(api_client: TestClient) -> None:
    """Ensure GET /playbook/rules/{rule_id} returns 404 for invalid ID."""
    response = api_client.get("/playbook/rules/NONEXISTENT-999")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "not found" in detail


@pytest.mark.anyio
async def test_api_search_and_reindex(api_client: TestClient) -> None:
    """Test POST /playbook/reindex and POST /playbook/search endpoints."""
    with tempfile.TemporaryDirectory() as tmp_chroma:
        with (
            patch("app.core.config.settings.CHROMA_PATH", tmp_chroma),
            patch(
                "app.services.vector_store.generate_embedding",
                new=AsyncMock(side_effect=fake_generate_embedding),
            ),
        ):
            # 1. Trigger Reindex
            reindex_res = api_client.post("/playbook/reindex", json={"rebuild": True})
            assert reindex_res.status_code == 200
            reindex_data = reindex_res.json()
            assert reindex_data["status"] == "ok"
            assert reindex_data["indexed_count"] == 13

            # 2. Trigger Search
            search_payload = {
                "clause_text": "Neither party shall be liable for indirect, incidental or lost profits.",
                "clause_type": "limitation_of_liability",
                "top_k": 2,
            }
            search_res = api_client.post("/playbook/search", json=search_payload)
            assert search_res.status_code == 200
            search_data = search_res.json()

            assert search_data["total_results"] <= 2
            assert search_data["clause_type"] == "limitation_of_liability"
            for item in search_data["results"]:
                assert "rule" in item
                assert "similarity_score" in item
                assert item["rule"]["clause_type"] == "limitation_of_liability"
                assert 0.0 <= item["similarity_score"] <= 1.0
