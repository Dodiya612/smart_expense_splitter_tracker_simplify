import sys
import unittest.mock
from typing import AsyncGenerator
import pytest
from httpx import ASGITransport, AsyncClient

# Mock uninstalled ML dependencies before importing app.main to prevent ModuleNotFoundError
for mod_name in (
    "joblib",
    "sklearn",
    "sklearn.feature_extraction",
    "sklearn.feature_extraction.text",
    "sklearn.linear_model",
    "sklearn.pipeline",
    "pandas",
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = unittest.mock.MagicMock()

from app.core.config import settings
from app.core.security_headers import API_CSP, DOCS_CSP, SecurityHeadersMiddleware
from app.main import app


@pytest.fixture
async def test_client() -> AsyncGenerator[AsyncClient, None]:
    """Dedicated AsyncClient fixture independent of external conftest."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.anyio
async def test_security_headers_present_on_root_200(test_client: AsyncClient):
    """Verify that all baseline security headers are present on a successful 200 response."""
    response = await test_client.get("/")
    assert response.status_code == 200

    # 1. MIME type sniffing protection
    assert response.headers.get("x-content-type-options") == "nosniff"

    # 2. Frame options / clickjacking protection
    assert response.headers.get("x-frame-options") == "DENY"

    # 3. Referrer policy
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    # 4. Permissions policy
    assert "camera=()" in response.headers.get("permissions-policy", "")
    assert "microphone=()" in response.headers.get("permissions-policy", "")
    assert "geolocation=()" in response.headers.get("permissions-policy", "")
    assert "payment=()" in response.headers.get("permissions-policy", "")

    # 5. Content Security Policy for API root
    assert response.headers.get("content-security-policy") == API_CSP


@pytest.mark.anyio
async def test_hsts_strictly_production_only(test_client: AsyncClient, monkeypatch):
    """
    Strict-Transport-Security must be emitted strictly in production.
    Must be absent in development, test, staging, or any non-production environment.
    """
    # 1. Development: Absent
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    r_dev = await test_client.get("/")
    assert "strict-transport-security" not in r_dev.headers

    # 2. Test: Absent
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    r_test = await test_client.get("/")
    assert "strict-transport-security" not in r_test.headers

    # 3. Staging: Absent
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    r_staging = await test_client.get("/")
    assert "strict-transport-security" not in r_staging.headers

    # 4. Production: Present (without includeSubDomains)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    r_prod = await test_client.get("/")
    assert r_prod.status_code == 200
    hsts = r_prod.headers.get("strict-transport-security")
    assert hsts is not None
    assert "max-age=31536000" in hsts
    assert "includesubdomains" not in hsts.lower()


@pytest.mark.anyio
async def test_security_headers_on_404_error(test_client: AsyncClient):
    """Verify that security headers are applied to 404 Not Found responses."""
    response = await test_client.get("/nonexistent-endpoint-path-xyz")
    assert response.status_code == 404
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert response.headers.get("content-security-policy") == API_CSP


@pytest.mark.anyio
async def test_security_headers_on_validation_error_422(test_client: AsyncClient):
    """Verify that security headers are applied to 422 Unprocessable Content validation error responses."""
    response = await test_client.post(
        "/api/v1/auth/login",
        json={"email": "invalid-email-format"},
    )
    assert response.status_code == 422
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("content-security-policy") == API_CSP


@pytest.mark.anyio
async def test_security_headers_on_method_not_allowed_405(test_client: AsyncClient):
    """Verify that security headers are applied to 405 Method Not Allowed responses."""
    response = await test_client.delete("/")
    assert response.status_code == 405
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"


@pytest.mark.anyio
async def test_security_headers_on_unhandled_500_response():
    """
    Verify that unhandled server exceptions (HTTP 500) caught by Starlette's
    ServerErrorMiddleware contain ALL required security headers and CORS headers.
    """
    # Define a test route on app that deliberately crashes with an unhandled exception
    @app.get("/api/v1/test-unhandled-500", include_in_schema=False)
    async def crash_endpoint():
        raise RuntimeError("Simulated unhandled critical failure")

    # Rebuild middleware stack so new route is included
    app.middleware_stack = app.build_middleware_stack()

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/v1/test-unhandled-500",
            headers={"Origin": "https://coinscious.vercel.app"},
        )
        assert response.status_code == 500

        # Standard error envelope
        data = response.json()
        assert data.get("code") == "INTERNAL_SERVER_ERROR"

        # Security headers must be present on 500 response
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "camera=()" in response.headers.get("permissions-policy", "")
        assert response.headers.get("content-security-policy") == API_CSP


@pytest.mark.anyio
async def test_cors_preflight_allowed_dev_origin(test_client: AsyncClient):
    """Verify CORS preflight succeeds for approved development origins with credentials."""
    response = await test_client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:8081",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8081"
    assert response.headers.get("access-control-allow-credentials") == "true"
    # Security headers must also be present on CORS preflight responses
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"


@pytest.mark.anyio
async def test_cors_preflight_allowed_prod_origin(monkeypatch):
    """Verify CORS preflight succeeds for production origin when configured in CORS_ORIGINS."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from starlette.types import ASGIApp

    class CustomTestApp(FastAPI):
        def build_middleware_stack(self) -> ASGIApp:
            stack = super().build_middleware_stack()
            return SecurityHeadersMiddleware(stack)

    test_app = CustomTestApp()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://coinscious.vercel.app"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/test",
            headers={
                "Origin": "https://coinscious.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://coinscious.vercel.app"
        assert response.headers.get("access-control-allow-credentials") == "true"
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"


@pytest.mark.anyio
async def test_cors_preflight_disallowed_origin(test_client: AsyncClient):
    """Verify CORS preflight rejects unauthorized/unapproved origins."""
    response = await test_client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://malicious-phishing-site.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Disallowed origins must not receive Access-Control-Allow-Origin
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.anyio
async def test_csp_documentation_vs_api(test_client: AsyncClient):
    """Verify that documentation endpoints receive Swagger-compatible CSP when docs are enabled."""
    if settings.docs_enabled:
        response = await test_client.get("/api/v1/docs")
        assert response.status_code == 200
        csp = response.headers.get("content-security-policy", "")
        assert "cdn.jsdelivr.net" in csp
        assert "'unsafe-inline'" in csp
        assert "frame-ancestors 'none'" in csp
    else:
        response = await test_client.get("/api/v1/docs")
        assert response.status_code == 404
        assert response.headers.get("content-security-policy") == API_CSP


@pytest.mark.anyio
async def test_docs_disabled_in_production(monkeypatch):
    """Verify that when documentation is disabled, docs and openapi routes are inaccessible."""
    monkeypatch.setattr(settings, "ENABLE_DOCS", False)

    from fastapi import FastAPI
    from starlette.types import ASGIApp

    class CustomProdApp(FastAPI):
        def build_middleware_stack(self) -> ASGIApp:
            stack = super().build_middleware_stack()
            return SecurityHeadersMiddleware(stack)

    prod_app = CustomProdApp(
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r_docs = await client.get("/api/v1/docs")
        assert r_docs.status_code == 404
        assert r_docs.headers.get("content-security-policy") == API_CSP

        r_redoc = await client.get("/api/v1/redoc")
        assert r_redoc.status_code == 404

        r_openapi = await client.get("/api/v1/openapi.json")
        assert r_openapi.status_code == 404


@pytest.mark.anyio
async def test_docs_enabled_property_behavior():
    """Verify docs_enabled defaults to True in dev, False in prod, unless explicitly set."""
    dummy_secret = "a" * 32
    dev_settings = settings.__class__(ENVIRONMENT="development", JWT_SECRET_KEY=dummy_secret)
    assert dev_settings.docs_enabled is True

    prod_settings = settings.__class__(ENVIRONMENT="production", JWT_SECRET_KEY=dummy_secret)
    assert prod_settings.docs_enabled is False

    override_prod = settings.__class__(ENVIRONMENT="production", ENABLE_DOCS=True, JWT_SECRET_KEY=dummy_secret)
    assert override_prod.docs_enabled is True

    override_dev = settings.__class__(ENVIRONMENT="development", ENABLE_DOCS=False, JWT_SECRET_KEY=dummy_secret)
    assert override_dev.docs_enabled is False


@pytest.mark.anyio
async def test_no_set_cookie_on_auth_endpoints(test_client: AsyncClient):
    """
    Verify that authentication endpoints return tokens in JSON bodies and DO NOT set cookies.
    Demonstrates that cookie security flags (Secure, HttpOnly, SameSite) are not applicable.
    """
    # 1. Login with invalid credentials
    response = await test_client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "Password123!"},
    )
    assert "set-cookie" not in response.headers

    # 2. Refresh token endpoint with invalid token
    refresh_response = await test_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": "fake-refresh-token"},
    )
    assert "set-cookie" not in refresh_response.headers
