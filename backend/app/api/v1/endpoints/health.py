from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import check_database_connection
from app.schemas.common import HealthResponse, MaintenanceBannerConfig

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Check the operational status of the API, maintenance state, and database connectivity.",
)
async def health_check(response: Response):
    db_connected, error = await check_database_connection()

    maintenance_info = MaintenanceBannerConfig(
        active=settings.MAINTENANCE_MODE,
        message=settings.MAINTENANCE_MESSAGE if settings.MAINTENANCE_MODE else None,
        start_time=settings.MAINTENANCE_START_TIME,
        end_time=settings.MAINTENANCE_END_TIME,
    )

    if settings.MAINTENANCE_MODE:
        response.headers["X-Maintenance-Mode"] = "1"

    if db_connected:
        status_str = "maintenance" if settings.MAINTENANCE_MODE else "healthy"
        return HealthResponse(
            status=status_str,
            database="connected",
            environment=settings.ENVIRONMENT,
            version=settings.VERSION,
            maintenance=maintenance_info,
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
            "maintenance": maintenance_info.model_dump(by_alias=True),
        },
        headers={"X-Maintenance-Mode": "1"} if settings.MAINTENANCE_MODE else None,
    )


@router.get(
    "/system/maintenance",
    response_model=MaintenanceBannerConfig,
    summary="Get Maintenance Banner Status",
    description="Returns the maintenance banner configuration for client applications (US-35 / T-61).",
)
async def get_maintenance_status():
    return MaintenanceBannerConfig(
        active=settings.MAINTENANCE_MODE,
        message=settings.MAINTENANCE_MESSAGE if settings.MAINTENANCE_MODE else None,
        start_time=settings.MAINTENANCE_START_TIME,
        end_time=settings.MAINTENANCE_END_TIME,
    )
