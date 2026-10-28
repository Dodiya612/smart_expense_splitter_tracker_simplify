from unittest.mock import patch
import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_check_healthy(client: AsyncClient):
    # Mock successful database connection
    with patch("app.api.v1.endpoints.health.check_database_connection", return_value=(True, None)):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert "environment" in data
        assert "version" in data


@pytest.mark.anyio
async def test_health_check_degraded(client: AsyncClient):
    # Mock database connection failure
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        return_value=(False, "Connection refused: database host unreachable"),
    ):
        response = await client.get("/api/v1/health")
        assert response.status_code == 503

        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "disconnected"
        assert "error" in data


@pytest.mark.anyio
async def test_root_endpoint(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert "name" in data
    assert "docsUrl" in data
    assert "healthUrl" in data


@pytest.mark.anyio
async def test_check_database_connection_offline_behavior():
    """Verify that when database is unreachable, check_database_connection returns (False, err_str)."""
    with patch(
        "app.core.database.AsyncSessionLocal",
        side_effect=Exception("Simulated network drop"),
    ):
        from app.core.database import check_database_connection
        is_connected, err = await check_database_connection()
        assert is_connected is False
        assert "Simulated network drop" in str(err)


@pytest.mark.anyio
async def test_genuine_postgresql_integration():
    """
    Genuine PostgreSQL integration test.
    Attempts an actual connection and query against the configured DATABASE_URL.
    Strictly asserts that the connection succeeds. Does NOT pass on connection failure.
    """
    from app.core.database import check_database_connection
    is_connected, err = await check_database_connection()
    assert is_connected is True, f"Live PostgreSQL connection failed: {err}"
    assert err is None
