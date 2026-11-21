"""Budgets (US-25 / T-48). Owner-only; anyone else gets 404."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.budget import (
    BudgetCreate,
    BudgetDataResponse,
    BudgetListMeta,
    BudgetListResponse,
    BudgetUpdate,
)
from app.services import budget_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100, description="Page size (1-100)")]
Offset = Annotated[int, Query(ge=0, le=100_000, description="Page offset")]


@router.get(
    "",
    response_model=BudgetListResponse,
    summary="List my budgets with current-period progress",
    description="Your active budgets, oldest first. Each shows spending (your share of every expense, "
    "never cash paid or settlements) for the current week (Monday to Sunday) or calendar month in "
    "Asia/Kolkata.",
)
async def list_budgets(current_user: CurrentUser, db: Db, limit: Limit = 50, offset: Offset = 0) -> BudgetListResponse:
    items, total = await budget_service.list_budgets(db, current_user, limit, offset)
    return BudgetListResponse(data=items, meta=BudgetListMeta(total=total, limit=limit, offset=offset))


@router.post(
    "",
    response_model=BudgetDataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a budget",
    description="A weekly or monthly limit, overall (omit categoryId) or for one category. At most one "
    "active budget per period and category (409 BUDGET_EXISTS). Alerts are sent at 80% and 100%, each "
    "once per period. Supports idempotent retries via the Idempotency-Key header (a replay adds "
    "X-Idempotent-Replay: true).",
)
async def create_budget(
    payload: BudgetCreate,
    response: Response,
    current_user: CurrentUser,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BudgetDataResponse:
    budget, is_replay = await budget_service.create_budget(db, current_user, payload, idempotency_key)
    if is_replay:
        response.headers["X-Idempotent-Replay"] = "true"
    return BudgetDataResponse(data=budget)


@router.get("/{budget_id}", response_model=BudgetDataResponse, summary="Get a budget with current-period progress")
async def get_budget(budget_id: uuid.UUID, current_user: CurrentUser, db: Db) -> BudgetDataResponse:
    return BudgetDataResponse(data=await budget_service.get_budget(db, current_user, budget_id))


@router.patch(
    "/{budget_id}",
    response_model=BudgetDataResponse,
    summary="Change a budget's limit",
    description="Only limitPaise can change; period, category, ownership and unknown fields are 422 "
    "(delete the budget and create a new one instead). A lower limit can send an alert at once; a "
    "higher limit never takes back an alert already sent this period.",
)
async def update_budget(
    budget_id: uuid.UUID, payload: BudgetUpdate, current_user: CurrentUser, db: Db
) -> BudgetDataResponse:
    return BudgetDataResponse(data=await budget_service.update_budget(db, current_user, budget_id, payload))


@router.delete(
    "/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a budget",
    description="The budget stops being tracked and its period and category can be budgeted again.",
)
async def delete_budget(budget_id: uuid.UUID, current_user: CurrentUser, db: Db) -> Response:
    await budget_service.delete_budget(db, current_user, budget_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
