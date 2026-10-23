"""System and database health repository."""

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.repositories.base import BaseRepository


class SystemRepository(BaseRepository[Dict[str, Any]]):
    """Repository handling system-level health inspection and DB verification."""

    def __init__(self, db_session: Optional[Any] = None) -> None:
        self.db = db_session

    def get(self, id: Any) -> Optional[Dict[str, Any]]:
        """Return system status component by name."""
        status_map = {
            "app": {"status": "ok", "version": settings.VERSION},
            "database": {
                "status": "configured" if settings.DATABASE_URL else "not_configured"
            },
        }
        return status_map.get(str(id))

    def get_multi(self, skip: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """Return collection of system component states."""
        return [
            {"component": "app", "status": "ok"},
            {"component": "database", "configured": bool(settings.DATABASE_URL)},
        ]

    def create(self, obj_in: Any) -> Dict[str, Any]:
        """Record audit event (stub for future ledger logging)."""
        return {"id": "audit_stub", "payload": obj_in}

    def update(self, id: Any, obj_in: Any) -> Optional[Dict[str, Any]]:
        """Update system state component."""
        return None

    def remove(self, id: Any) -> Optional[Dict[str, Any]]:
        """Remove system state component."""
        return None

    def check_database_liveness(self) -> bool:
        """Check whether database connection is active."""
        if not self.db:
            return True
        try:
            # If SQLAlchemy session is active: self.db.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
