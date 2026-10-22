"""Health check endpoint for liveness and deployment verification."""

from datetime import datetime, timezone

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    """Minimal health status response without sensitive information."""

    status: str
    environment: str
    version: str
    timestamp: str


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Health Check",
    description=(
        "Returns service liveness status and environment indicator "
        "for deployment health checks."
    ),
)
def get_health() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="ok",
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
