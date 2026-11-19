"""Idempotency-Key handling for create endpoints (US-34 / T-38).

Same behaviour as the personal expense and settlement creates:
- the key is optional; requests without it behave exactly as before;
- a repeated key with the same request replays the stored original response
  (the route adds ``X-Idempotent-Replay: true``);
- the same key with a different request is ``409 IDEMPOTENCY_CONFLICT``;
- the idempotency record is staged in the caller's session, so it commits in the
  same transaction as the rows it protects (or not at all).

Records live in the existing ``idempotency_records`` table (unique per user + key).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idempotency import IdempotencyRecord

logger = logging.getLogger(__name__)

ResponseT = TypeVar("ResponseT", bound=BaseModel)

MAX_KEY_LENGTH = 255  # idempotency_records.key is VARCHAR(255)


def normalize_key(idempotency_key: str) -> str:
    """Strip the key and reject empty or over-long keys with 400 INVALID_IDEMPOTENCY_KEY."""
    key = idempotency_key.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "Idempotency-Key must be between 1 and 255 characters.",
            },
        )
    return key


def request_hash(kind: str, user_id: uuid.UUID, scope_id: uuid.UUID | None, payload: BaseModel) -> str:
    """Deterministic SHA-256 of what is being created, by whom, and where."""
    canonical: dict[str, Any] = {
        "kind": kind,
        "user_id": str(user_id),
        "scope_id": str(scope_id) if scope_id else None,
        "payload": payload.model_dump(mode="json"),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()


def _conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key has already been used with a different request payload.",
        },
    )


async def find_replay(
    db: AsyncSession,
    user_id: uuid.UUID,
    idempotency_key: str,
    hashed_request: str,
    response_model: type[ResponseT],
) -> ResponseT | None:
    """Stored response for a repeated key; 409 if the key was used for a different request."""
    result = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    if record.request_hash != hashed_request:
        raise _conflict()
    try:
        return response_model.model_validate(json.loads(record.response_body))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Stored idempotent response for key could not be parsed: %s", exc)
        raise _conflict() from exc


async def prepare(
    db: AsyncSession,
    user_id: uuid.UUID,
    idempotency_key: str | None,
    kind: str,
    scope_id: uuid.UUID | None,
    payload: BaseModel,
    response_model: type[ResponseT],
) -> tuple[str | None, str | None, ResponseT | None]:
    """Before creating: returns (normalized key, request hash, stored replay or None).

    Without a key returns (None, None, None) and the create proceeds as before.
    """
    if idempotency_key is None:
        return None, None, None
    key = normalize_key(idempotency_key)
    hashed = request_hash(kind, user_id, scope_id, payload)
    return key, hashed, await find_replay(db, user_id, key, hashed, response_model)


async def replay_after_conflict(
    db: AsyncSession,
    user_id: uuid.UUID,
    idempotency_key: str | None,
    hashed_request: str | None,
    response_model: type[ResponseT],
) -> ResponseT | None:
    """After a rolled-back IntegrityError: the winner's response if a concurrent
    request with the same key committed first, else None (caller re-raises)."""
    if not idempotency_key or not hashed_request:
        return None
    return await find_replay(db, user_id, idempotency_key, hashed_request, response_model)


def stage_record(
    db: AsyncSession,
    user_id: uuid.UUID,
    idempotency_key: str,
    hashed_request: str,
    response: BaseModel,
    resource_id: uuid.UUID,
    response_code: int = status.HTTP_201_CREATED,
) -> None:
    """Add the idempotency record to the caller's open transaction (committed with it)."""
    db.add(
        IdempotencyRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            key=idempotency_key,
            request_hash=hashed_request,
            response_code=response_code,
            response_body=json.dumps(response.model_dump(mode="json")),
            resource_id=resource_id,
            created_at=datetime.now(UTC),
        )
    )
