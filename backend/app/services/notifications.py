"""Persistent in-app notifications (US-38 / T-36).

Writers call ``emit()`` / ``notify_users()`` / ``notify_group_members()`` AFTER their
transaction has committed, so a failed or rolled-back save never produces a
notification, and a failure here never turns a saved record into an error response:
every failure is logged and swallowed.

Notifications are stored in their own short transaction (a separate session), one row
per (user, event). Deduplication is enforced by the database: the unique constraint on
``(user_id, dedupe_key)`` plus ``INSERT ... ON CONFLICT DO NOTHING`` make concurrent
requests and retries safe. A user's explicit "off" preference for a kind means no row
is inserted; no preference row means enabled.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.models.notification import (
    NOTIFICATION_KINDS,
    SECURITY_KINDS,
    Notification,
    NotificationPreference,
)

if TYPE_CHECKING:
    from app.models.group import Group

logger = logging.getLogger("app.notifications")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class NotificationEvent:
    user_id: str
    kind: str
    ref: str
    dedupe_key: str
    payload: Dict[str, Any] = field(default_factory=dict)
    group_id: Optional[str] = None
    title: str = ""
    body: str = ""
    created_at: datetime = field(default_factory=utcnow)


def format_inr(amount_paise: Any) -> str:
    """Format integer paise as a rupee string for notification text (display only)."""
    try:
        paise = int(amount_paise)
    except (TypeError, ValueError):
        return ""
    rupees, rem = divmod(abs(paise), 100)
    text = f"{rupees:,}" if rem == 0 else f"{rupees:,}.{rem:02d}"
    return f"₹{text}" if paise >= 0 else f"-₹{text}"


def render_notification(kind: str, payload: Dict[str, Any]) -> tuple[str, str]:
    """Build the display title and body for a notification from its payload."""
    actor = payload.get("actor_name") or "Someone"
    group = payload.get("group_name") or "your group"
    description = payload.get("description") or "an expense"
    amount = format_inr(payload.get("amount_paise"))
    amount_part = f" ({amount})" if amount else ""
    target = payload.get("target_name") or "A member"

    if kind == "group_expense_created":
        return f"New expense in {group}", f"{actor} added {description}{amount_part}."
    if kind == "group_expense_updated":
        return f"Expense updated in {group}", f"{actor} updated {description}{amount_part}."
    if kind == "group_expense_deleted":
        return f"Expense deleted in {group}", f"{actor} deleted {description}{amount_part}."
    if kind == "settlement_recorded":
        return (
            f"Settlement recorded in {group}",
            f"{actor} recorded a settlement of {amount or 'an amount'}.",
        )
    if kind == "member_joined":
        return f"New member in {group}", f"{actor} joined the group."
    if kind == "invitation_received":
        return f"Invitation to {group}", f"{actor} invited you to join {group}."
    if kind == "invitation_accepted":
        return "Invitation accepted", f"{actor} accepted your invitation to {group}."
    if kind == "invitation_declined":
        return "Invitation declined", f"{actor} declined your invitation to {group}."
    if kind == "member_removed":
        if payload.get("you"):
            return f"Removed from {group}", f"{actor} removed you from {group}."
        return f"Member removed from {group}", f"{actor} removed {target} from {group}."
    if kind == "member_left":
        return f"Member left {group}", f"{actor} left the group."
    if kind == "password_changed":
        signed_out = payload.get("revoked_sessions")
        if isinstance(signed_out, int) and not isinstance(signed_out, bool) and signed_out > 0:
            devices = "device" if signed_out == 1 else "devices"
            detail = f" You were signed out on {signed_out} other {devices}."
        else:
            detail = ""
        return (
            "Password changed",
            f"Your account password was changed.{detail} "
            "If you did not make this change, secure your account immediately.",
        )
    if kind == "recurring_expense_upcoming":
        on = payload.get("occurrence_date") or "tomorrow"
        return "Upcoming recurring expense", f"{description}{amount_part} will be added on {on}."
    if kind == "recurring_expense_skipped":
        on = payload.get("occurrence_date") or "its date"
        reason = payload.get("reason_text") or "it could not be created"
        return "Recurring expense skipped", f"{description}{amount_part} for {on} was not added: {reason}."
    return "Notification", ""


def _parse_uuid(value: Any) -> Optional[uuid.UUID]:
    """Return a UUID, or None if the value is not one (never raises)."""
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _log_failure(message: str, exc: BaseException, **context: Any) -> None:
    """Log a notification failure without leaking data.

    Only the exception class (and the SQLSTATE for database errors) is logged at ERROR:
    SQLAlchemy error text embeds the statement parameters, which here contain titles,
    bodies and payloads. The full traceback is available at DEBUG for local diagnosis.
    """
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    details = " ".join(f"{k}={v}" for k, v in context.items())
    logger.error(
        "%s (%s%s) %s",
        message,
        type(exc).__name__,
        f", sqlstate={sqlstate}" if sqlstate else "",
        details,
    )
    logger.debug("%s - traceback", message, exc_info=exc)


async def _persist(events: List[NotificationEvent]) -> List[NotificationEvent]:
    """Insert events in their own transaction; return those actually stored.

    Skips users who switched the kind off (never for SECURITY_KINDS), events whose
    (user, dedupe_key) already exists, and events with an invalid recipient or group id.
    Each insert runs in its own savepoint, so one failing recipient cannot poison the
    session or stop the valid ones.
    """
    ready: List[tuple[NotificationEvent, uuid.UUID, Optional[uuid.UUID]]] = []
    for event in events:
        user_uuid = _parse_uuid(event.user_id)
        group_uuid = _parse_uuid(event.group_id) if event.group_id else None
        if user_uuid is None or (event.group_id and group_uuid is None):
            logger.error(
                "Notification skipped: invalid recipient or group id kind=%s ref=%s",
                event.kind,
                event.ref,
            )
            continue
        ready.append((event, user_uuid, group_uuid))
    if not ready:
        return []

    inserted: List[NotificationEvent] = []
    async with AsyncSessionLocal() as session:
        off = await session.execute(
            select(NotificationPreference.user_id, NotificationPreference.kind).where(
                NotificationPreference.user_id.in_({u for _, u, _ in ready}),
                NotificationPreference.kind.in_({e.kind for e, _, _ in ready}),
                NotificationPreference.enabled.is_(False),
            )
        )
        disabled = {(uid, kind) for uid, kind in off.all()}

        for event, user_uuid, group_uuid in ready:
            if event.kind not in SECURITY_KINDS and (user_uuid, event.kind) in disabled:
                continue
            try:
                async with session.begin_nested():
                    result = await session.execute(
                        pg_insert(Notification)
                        .values(
                            id=uuid.uuid4(),
                            user_id=user_uuid,
                            group_id=group_uuid,
                            kind=event.kind,
                            title=event.title,
                            body=event.body,
                            payload=event.payload,
                            dedupe_key=event.dedupe_key,
                            created_at=event.created_at,
                        )
                        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
                        .returning(Notification.id)
                    )
                    if result.scalar_one_or_none() is not None:
                        inserted.append(event)
            except Exception as exc:  # noqa: BLE001 - one bad recipient must not block the others
                _log_failure(
                    "Notification insert failed", exc, kind=event.kind, ref=event.ref, user=event.user_id
                )
        await session.commit()
    return inserted


async def _deliver(events: List[NotificationEvent]) -> List[NotificationEvent]:
    """Persist events; log and swallow any failure (the business record is already committed)."""
    try:
        return await _persist(events)
    except Exception as exc:  # noqa: BLE001 - never fail a committed request because of a notice
        _log_failure("Notification delivery failed; the saved record is kept", exc, count=len(events))
        return []


def _build_event(
    user: uuid.UUID | str,
    kind: str,
    ref: str,
    dedupe_key: str,
    payload: Optional[Dict[str, Any]],
    group_id: uuid.UUID | str | None,
) -> NotificationEvent:
    if kind not in NOTIFICATION_KINDS:
        raise ValueError(f"Unknown notification kind: {kind}")
    user_uuid = _parse_uuid(user)
    if user_uuid is None:
        raise ValueError("Invalid recipient id")
    data = dict(payload or {})
    if group_id is None and data.get("group_id"):
        group_id = data["group_id"]
    group_uuid = _parse_uuid(group_id) if group_id else None
    if group_id and group_uuid is None:
        raise ValueError("Invalid group id")
    title, body = render_notification(kind, data)
    return NotificationEvent(
        user_id=str(user_uuid),
        kind=kind,
        ref=ref,
        dedupe_key=dedupe_key,
        payload=data,
        group_id=str(group_uuid) if group_uuid else None,
        title=title,
        body=body,
    )


async def emit(
    user: uuid.UUID | str,
    kind: str,
    ref: str,
    dedupe_key: str,
    payload: Optional[Dict[str, Any]] = None,
    group_id: uuid.UUID | str | None = None,
) -> bool:
    """Store one notification for one user. Returns True if a new row was stored.

    Call after the related transaction commits. Returns False if the user turned this
    kind off, the same dedupe_key was already stored for that user, or storing failed.
    """
    try:
        event = _build_event(user, kind, ref, dedupe_key, payload, group_id)
    except Exception as exc:  # noqa: BLE001
        _log_failure("Notification could not be built", exc, kind=kind, ref=ref)
        return False
    return bool(await _deliver([event]))


async def notify_users(
    user_ids: Iterable[uuid.UUID | str],
    actor_id: Optional[uuid.UUID],
    kind: str,
    ref: str,
    payload: Optional[Dict[str, Any]] = None,
    group_id: uuid.UUID | str | None = None,
) -> List[NotificationEvent]:
    """Notify each distinct recipient except the actor, in one post-commit batch.

    The dedupe key is ``kind:ref:user_id``; callers put whatever makes the event unique
    in ``ref`` (for example the expense id plus its new version).
    """
    actor = str(actor_id) if actor_id else None
    recipients: List[str] = []
    for uid in user_ids:
        parsed = _parse_uuid(uid)
        if parsed is None:
            # An invalid recipient is skipped; the valid ones in the batch still get notified.
            logger.error("Notification skipped: invalid recipient id kind=%s ref=%s", kind, ref)
            continue
        sid = str(parsed)
        if sid != actor and sid not in recipients:
            recipients.append(sid)

    data = dict(payload or {})
    data["actor_id"] = actor
    events: List[NotificationEvent] = []
    for sid in recipients:
        try:
            events.append(_build_event(sid, kind, ref, f"{kind}:{ref}:{sid}", data, group_id))
        except Exception as exc:  # noqa: BLE001
            _log_failure("Notification could not be built", exc, kind=kind, ref=ref, user=sid)
    return await _deliver(events)


async def active_member_roles(db: AsyncSession, group_id: uuid.UUID) -> Dict[uuid.UUID, str]:
    """Committed ACTIVE membership of a group: {user_id: role}, read from the database.

    This is a column query on purpose. A loaded ``Group.members`` collection is a
    snapshot from when the request started and is never refreshed by a later
    ``get_group_or_404`` (the session keeps ``expire_on_commit=False``), so it can miss
    a member who joined, or still list one who was removed, while the request ran.
    Column results are not served from the identity map, so they are always current.
    """
    from app.models.group import GroupMember, GroupMemberStatus

    result = await db.execute(
        select(GroupMember.user_id, GroupMember.role).where(
            GroupMember.group_id == group_id,
            GroupMember.status == GroupMemberStatus.ACTIVE.value,
        )
    )
    return {user_id: role for user_id, role in result.all()}


async def current_member_roles(
    db: Optional[AsyncSession], group: Group
) -> Dict[uuid.UUID, str]:
    """Active members {user_id: role} for a post-commit notice.

    Prefers the committed state from the database. If that read fails, or no session is
    given, falls back to the snapshot on ``group.members`` and logs the fallback.
    """
    from app.models.group import GroupMemberStatus

    if db is not None:
        try:
            roles = await active_member_roles(db, group.id)
            if roles is not None:
                return roles
        except Exception as exc:  # noqa: BLE001 - never fail a committed request
            _log_failure("Fresh membership lookup failed; using loaded members", exc, group=group.id)
    return {
        m.user_id: m.role
        for m in (group.members or [])
        if m.status == GroupMemberStatus.ACTIVE.value
    }


async def notify_group_members(
    group: Group,
    actor_id: Optional[uuid.UUID],
    kind: str,
    ref: str,
    payload: Optional[Dict[str, Any]] = None,
    exclude: Iterable[uuid.UUID | str] = (),
    db: Optional[AsyncSession] = None,
) -> List[NotificationEvent]:
    """Notify the group's ACTIVE members (not the actor, not ``exclude``) after a commit.

    Pass ``db`` so recipients come from the committed membership instead of the
    possibly stale ``group.members`` snapshot.
    """
    skip = {str(x) for x in exclude}
    roles = await current_member_roles(db, group)
    members = [uid for uid in roles if str(uid) not in skip]
    data = dict(payload or {})
    data["group_id"] = str(group.id)
    data.setdefault("group_name", group.name)
    return await notify_users(members, actor_id, kind, ref, data, group_id=group.id)
