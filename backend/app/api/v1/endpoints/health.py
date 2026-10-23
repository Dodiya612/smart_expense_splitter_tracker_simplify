"""Health check endpoint for liveness and deployment verification."""

from fastapi import APIRouter, Depends, status

from app.schemas.errors import ErrorResponse
from app.schemas.health import HealthResponse
from app.services.health import HealthService, get_health_service

router = APIRouter()


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Service Health Check",
    description=(
        "Returns service liveness status and environment indicator "
        "for deployment health checks."
    ),
    responses={
        200: {
            "model": HealthResponse,
            "description": "Service is live and operational.",
        },
        500: {
            "model": ErrorResponse,
            "description": "Internal server error envelope.",
        },
    },
)
def check_health(
    service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    """Return service health status via HealthService."""
    return service.get_health()
