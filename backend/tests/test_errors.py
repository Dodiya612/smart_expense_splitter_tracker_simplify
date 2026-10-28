import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_not_found_error_envelope(client: AsyncClient):
    response = await client.get("/api/v1/non-existent-route")
    assert response.status_code == 404

    data = response.json()
    assert "code" in data
    assert "message" in data
    assert "isRetryable" in data
    assert data["isRetryable"] is False
    assert data["detail"] is None


@pytest.mark.anyio
async def test_cors_preflight_headers(client: AsyncClient):
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8081"
    assert response.headers.get("access-control-allow-credentials") == "true"


@pytest.mark.anyio
async def test_cors_rejection_for_unauthorized_origin(client: AsyncClient):
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://malicious-website.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Origin should not be allowed
    assert response.headers.get("access-control-allow-origin") is None
