"""Notification centre endpoints (US-38 / T-36).

Every query is filtered by the authenticated user's id (from the bearer token, never
from the client). A notification that belongs to someone else is reported as 404 so
ids cannot be probed.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.notification import (
    NOTIFICATION_KINDS,
    SECURITY_KINDS,
    Notification,
    NotificationPreference,
    utcnow,
)
from app.models.user import User
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationPreferencesUpdateRequest,
    NotificationPreferenceResponse,
    NotificationResponse,
    UnreadCountResponse,
)

router = APIRouter()
preferences_router = APIRouter()


def _to_response(row: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=row.id,
        kind=row.kind,
        title=row.title,
        body=row.body,
        payload=row.payload or {},
        group_id=row.group_id,
        is_read=row.read_at is not None,
        read_at=row.read_at,
        created_at=row.created_at,
    )


def _encode_cursor(row: Notification) -> str:
    raw = f"{row.created_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        ts, _, ident = raw.partition("|")
        return datetime.fromisoformat(ts), uuid.UUID(ident)
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CURSOR", "message": "Invalid pagination cursor."},
        ) from exc


async def _unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(result.scalar_one())


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "NOTIFICATION_NOT_FOUND", "message": "Notification not found."},
    )


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="List my notifications (newest first)",
)
async def list_notifications(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    unread_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if cursor:
        ts, ident = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Notification.created_at < ts,
                and_(Notification.created_at == ts, Notification.id < ident),
            )
        )
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return NotificationListResponse(
        items=[_to_response(r) for r in rows],
        next_cursor=_encode_cursor(rows[-1]) if has_more and rows else None,
        unread_count=await _unread_count(db, current_user.id),
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Number of my unread notifications",
)
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    return UnreadCountResponse(unread_count=await _unread_count(db, current_user.id))


@router.patch(
    "/read-all",
    response_model=MarkAllReadResponse,
    summary="Mark all my notifications as read",
)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MarkAllReadResponse:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    await db.commit()
    return MarkAllReadResponse(updated=result.rowcount or 0)


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
    summary="Mark one of my notifications as read",
)
async def mark_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _not_found()
    if row.read_at is None:  # idempotent: keep the first read time
        row.read_at = utcnow()
        await db.commit()
    return _to_response(row)


async def _load_preferences(db: AsyncSession, user_id: uuid.UUID) -> NotificationPreferencesResponse:
    rows = (
        await db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
    ).scalars().all()
    stored = {r.kind: r.enabled for r in rows}
    return NotificationPreferencesResponse(
        preferences=[
            NotificationPreferenceResponse(
                kind=kind,
                enabled=True if kind in SECURITY_KINDS else stored.get(kind, True),
                can_disable=kind not in SECURITY_KINDS,
            )
            for kind in NOTIFICATION_KINDS
        ]
    )


@preferences_router.get(
    "",
    response_model=NotificationPreferencesResponse,
    summary="Get my notification settings",
)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesResponse:
    return await _load_preferences(db, current_user.id)


@preferences_router.put(
    "",
    response_model=NotificationPreferencesResponse,
    summary="Update my notification settings",
)
async def update_preferences(
    payload: NotificationPreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPreferencesResponse:
    now = utcnow()
    for item in payload.preferences:
        stmt = pg_insert(NotificationPreference).values(
            user_id=current_user.id, kind=item.kind, enabled=item.enabled, updated_at=now
        )
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "kind"],
                set_={"enabled": item.enabled, "updated_at": now},
            )
        )
    await db.commit()
    return await _load_preferences(db, current_user.id)
