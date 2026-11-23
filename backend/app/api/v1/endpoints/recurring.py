"""Recurring expense rules (US-14 / T-44). Owner-only; anyone else gets 404."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.recurring import (
    RecurringListMeta,
    RecurringOccurrenceListResponse,
    RecurringRuleCreate,
    RecurringRuleDataResponse,
    RecurringRuleListResponse,
    RecurringRuleUpdate,
)
from app.services import recurring_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100, description="Page size (1-100)")]
Offset = Annotated[int, Query(ge=0, le=100_000, description="Page offset")]


@router.post(
    "",
    response_model=RecurringRuleDataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring expense rule",
    description="Creates a daily, weekly, monthly or yearly rule (personal, or a group expense with "
    "its split). The first occurrence is start_date. Supports idempotent retries via the "
    "Idempotency-Key header (a replay adds X-Idempotent-Replay: true).",
)
async def create_rule(
    payload: RecurringRuleCreate,
    response: Response,
    current_user: CurrentUser,
    db: Db,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RecurringRuleDataResponse:
    rule, is_replay = await recurring_service.create_rule(db, current_user, payload, idempotency_key)
    if is_replay:
        response.headers["X-Idempotent-Replay"] = "true"
    return RecurringRuleDataResponse(data=rule)


@router.get(
    "",
    response_model=RecurringRuleListResponse,
    summary="List my recurring expense rules",
    description="Your rules with their status and next run date, newest first.",
)
async def list_rules(
    current_user: CurrentUser,
    db: Db,
    rule_status: Annotated[
        Literal["active", "paused", "cancelled"] | None, Query(alias="status", description="Filter by status")
    ] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> RecurringRuleListResponse:
    rules, total = await recurring_service.list_rules(db, current_user, rule_status, limit, offset)
    return RecurringRuleListResponse(data=rules, meta=RecurringListMeta(total=total, limit=limit, offset=offset))


@router.get("/{rule_id}", response_model=RecurringRuleDataResponse, summary="Get a recurring expense rule")
async def get_rule(rule_id: uuid.UUID, current_user: CurrentUser, db: Db) -> RecurringRuleDataResponse:
    return RecurringRuleDataResponse(data=await recurring_service.get_rule(db, current_user, rule_id))


@router.patch(
    "/{rule_id}",
    response_model=RecurringRuleDataResponse,
    summary="Edit a recurring expense rule (future occurrences only)",
    description="Changes amount, category, description, notes, merchant, payment mode, end date or "
    "(group rules) split. Expenses already created are not modified. A cancelled rule cannot be edited.",
)
async def update_rule(
    rule_id: uuid.UUID, payload: RecurringRuleUpdate, current_user: CurrentUser, db: Db
) -> RecurringRuleDataResponse:
    return RecurringRuleDataResponse(data=await recurring_service.update_rule(db, current_user, rule_id, payload))


@router.post(
    "/{rule_id}/pause",
    response_model=RecurringRuleDataResponse,
    summary="Pause a recurring expense rule",
    description="No occurrences and no reminders are produced while paused.",
)
async def pause_rule(rule_id: uuid.UUID, current_user: CurrentUser, db: Db) -> RecurringRuleDataResponse:
    return RecurringRuleDataResponse(data=await recurring_service.change_status(db, current_user, rule_id, "pause"))


@router.post(
    "/{rule_id}/resume",
    response_model=RecurringRuleDataResponse,
    summary="Resume a paused recurring expense rule",
    description="Continues from the next scheduled date on or after today; the paused period is not back-filled.",
)
async def resume_rule(rule_id: uuid.UUID, current_user: CurrentUser, db: Db) -> RecurringRuleDataResponse:
    return RecurringRuleDataResponse(data=await recurring_service.change_status(db, current_user, rule_id, "resume"))


@router.post(
    "/{rule_id}/cancel",
    response_model=RecurringRuleDataResponse,
    summary="Cancel a recurring expense rule (final)",
)
async def cancel_rule(rule_id: uuid.UUID, current_user: CurrentUser, db: Db) -> RecurringRuleDataResponse:
    return RecurringRuleDataResponse(data=await recurring_service.change_status(db, current_user, rule_id, "cancel"))


@router.get(
    "/{rule_id}/occurrences",
    response_model=RecurringOccurrenceListResponse,
    summary="Occurrence history of a recurring expense rule",
    description="Each handled date with the created expense id, or the reason it was skipped. Newest first.",
)
async def list_occurrences(
    rule_id: uuid.UUID, current_user: CurrentUser, db: Db, limit: Limit = 50, offset: Offset = 0
) -> RecurringOccurrenceListResponse:
    items, total = await recurring_service.list_occurrences(db, current_user, rule_id, limit, offset)
    return RecurringOccurrenceListResponse(data=items, meta=RecurringListMeta(total=total, limit=limit, offset=offset))
