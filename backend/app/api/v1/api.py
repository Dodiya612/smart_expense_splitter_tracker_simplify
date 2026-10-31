from fastapi import APIRouter

from app.api.v1.endpoints import ai, auth, expenses, health

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(expenses.router, prefix="/expenses", tags=["Expenses"])
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
