from fastapi import APIRouter

from app.api.v1.endpoints import ai, auth, expenses, groups, health, invitations

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(expenses.router, prefix="/expenses", tags=["Expenses"])
api_router.include_router(groups.router, prefix="/groups", tags=["Groups"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["Invitations"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
