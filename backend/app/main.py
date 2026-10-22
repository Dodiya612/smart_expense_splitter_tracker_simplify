"""Main FastAPI application entrypoint."""

import os

import uvicorn
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api import api_router
from app.api.v1.endpoints.health import HealthResponse, get_health
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS
    if isinstance(settings.CORS_ORIGINS, list)
    else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 router (includes /api/v1/health)
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
    """Top-level health alias delegating to /api/v1/health."""
    return get_health()


if __name__ == "__main__":
    # Render and hosting providers set the PORT environment variable dynamically
    port = int(os.environ.get("PORT", settings.PORT))
    host = os.environ.get("HOST", settings.HOST)
    uvicorn.run("app.main:app", host=host, port=port, reload=settings.DEBUG)
