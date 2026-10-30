"""Re-export expense router for compatibility with both endpoints and routers conventions."""
from app.api.v1.endpoints.expenses import router

__all__ = ["router"]

