"""Main FastAPI application entrypoint."""

import os

import uvicorn
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.middleware import RequestIDMiddleware
from app.schemas.health import HealthResponse
from app.services.health import HealthService

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Coinscious Backend API — Smart Expense Splitter & Tracker.\n\n"
        "Features typed routes, repository/service architecture, "
        "consistent error responses, and automated OpenAPI client generation."
    ),
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# 1. Register Request ID Middleware
app.add_middleware(RequestIDMiddleware)

# 2. Register CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS
    if isinstance(settings.CORS_ORIGINS, list)
    else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# 3. Register Global Error Handlers (Consistent Error Envelope)
register_error_handlers(app)

# 4. Mount API v1 Routers (including /api/v1/health)
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="Root Service Info",
    include_in_schema=False,
)
def root():
    """Root info endpoint providing service status and links."""
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "environment": settings.ENVIRONMENT,
        "health": f"{settings.API_V1_STR}/health",
        "docs": f"{settings.API_V1_STR}/docs",
        "openapi": f"{settings.API_V1_STR}/openapi.json",
    }


# Convenience alias for platforms checking top-level /health
@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness Check (Root Alias)",
    include_in_schema=False,
)
def health_alias() -> HealthResponse:
    """Top-level health alias delegating to HealthService."""
    return HealthService().get_health()


def custom_openapi():
    """Generate cached custom OpenAPI schema with clean metadata."""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    # Add servers configuration
    openapi_schema["servers"] = [
        {"url": "/", "description": "Current Server Environment"},
        {"url": "http://localhost:8000", "description": "Local Development"},
        {
            "url": "https://coinscious-backend.onrender.com",
            "description": "Production (Render)",
        },
    ]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


if __name__ == "__main__":
    # Render and hosting providers set the PORT environment variable dynamically
    port = int(os.environ.get("PORT", settings.PORT))
    host = os.environ.get("HOST", settings.HOST)
    uvicorn.run("app.main:app", host=host, port=port, reload=settings.DEBUG)
