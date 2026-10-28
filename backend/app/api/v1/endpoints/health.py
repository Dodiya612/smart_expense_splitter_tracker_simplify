from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import check_database_connection
from app.schemas.common import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Check the operational status of the API and its database connectivity.",
)
async def health_check():
    db_connected, error = await check_database_connection()

    if db_connected:
        return HealthResponse(
            status="healthy",
            database="connected",
            environment=settings.ENVIRONMENT,
            version=settings.VERSION,
        )

    # If database is not reachable, report degraded status with 503 Service Unavailable
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "degraded",
            "database": "disconnected",
            "environment": settings.ENVIRONMENT,
            "version": settings.VERSION,
            "error": error,
        },
    )
