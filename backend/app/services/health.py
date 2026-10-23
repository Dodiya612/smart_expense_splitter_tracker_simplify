"""Health service coordinating health check and liveness verification."""

from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.repositories.system import SystemRepository
from app.schemas.health import HealthResponse
from app.services.base import BaseService


class HealthService(BaseService):
    """Service providing liveness inspection and system health reporting."""

    def __init__(self, repository: Optional[SystemRepository] = None) -> None:
        super().__init__(repository=repository or SystemRepository())

    def get_health(self) -> HealthResponse:
        """Inspect system status and return safe HealthResponse."""
        return HealthResponse(
            status="ok",
            environment=settings.ENVIRONMENT,
            version=settings.VERSION,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


def get_health_service() -> HealthService:
    """Dependency provider for HealthService."""
    return HealthService()
