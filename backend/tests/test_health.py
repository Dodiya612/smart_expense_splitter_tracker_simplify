"""Tests for the health check and root endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_endpoint():
    """Verify GET /api/v1/health returns 200 OK with minimal status information."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "environment" in data
    assert "version" in data
    assert "timestamp" in data

    # Verify no secrets or database credentials are exposed
    assert "database" not in data
    assert "key" not in data
    assert "secret" not in data
    assert "password" not in data


def test_health_alias_endpoint():
    """Verify top-level GET /health alias functions correctly for monitors."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root_endpoint():
    """Verify GET / returns 200 OK with service info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "service" in data
    assert data["health"] == "/api/v1/health"
