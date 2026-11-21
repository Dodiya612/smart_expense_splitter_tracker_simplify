"""Budgets endpoint stub (required for import in api.py)."""

from fastapi import APIRouter

router = APIRouter()

@router.get("/dummy")
async def dummy() -> dict:
    """Placeholder endpoint so the module can be imported.
    The real budgets implementation will be added later.
    """
    return {"msg": "budgets endpoint placeholder"}
