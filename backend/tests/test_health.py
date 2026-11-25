"""Tests for the /health endpoint and basic application configuration."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_health_endpoint() -> None:
    """Ensure GET /health returns 200 OK and expected status payload."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == settings.APP_NAME
    assert data["llm_provider"] == "gemini"
    assert "ADVISORY ONLY" in data["disclaimer"]


def test_root_endpoint() -> None:
    """Ensure GET / returns 200 OK with links and disclaimer."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["health"] == "/health"
    assert data["docs"] == "/docs"
    assert "ADVISORY ONLY" in data["disclaimer"]
