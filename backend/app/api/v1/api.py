from fastapi import APIRouter

from app.api.v1.endpoints import (
    ai,
    analytics,
    analytics_tools,
    auth,
    budgets,
    expenses,
    groups,
    health,
    invitations,
    notifications,
    receipts,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(expenses.router, prefix="/expenses", tags=["Expenses"])
api_router.include_router(receipts.router, prefix="/receipts", tags=["Receipts"])
api_router.include_router(groups.router, prefix="/groups", tags=["Groups"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["Invitations"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(analytics_tools.router, prefix="/analytics-tools", tags=["Analytics Tools"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_router.include_router(
    notifications.preferences_router,
    prefix="/notification-preferences",
    tags=["Notifications"],
)
