from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

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
    created_at: datetime = field(default_factory=utcnow)


# In-memory registry for notifications and event deduplication (per US-38 specification)
_emitted_notifications: List[NotificationEvent] = []
_processed_dedupe_keys: Set[str] = set()


def clear_emitted_notifications() -> None:
    """Clear all emitted notifications and processed dedupe keys (for test resets)."""
    _emitted_notifications.clear()
    _processed_dedupe_keys.clear()


def get_emitted_notifications() -> List[NotificationEvent]:
    """Return a shallow copy of all emitted notifications."""
    return list(_emitted_notifications)


def emit(
    user: uuid.UUID | str,
    kind: str,
    ref: str,
    dedupe_key: str,
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """Emit a notification to a specific user.

    As defined in docs/coinscious-product-document-equal.html (US-38, T-36):
    - Unique dedupe key per event ensures the same event never notifies twice.
    - Writers call emit() after their transaction commits, so a failed notice never undoes a saved expense.
    """
    clean_user = str(user)
    if dedupe_key in _processed_dedupe_keys:
        logger.info(
            "Notification deduplicated: dedupe_key '%s' already sent to user '%s'.",
            dedupe_key,
            clean_user,
        )
        return False

    event = NotificationEvent(
        user_id=clean_user,
        kind=kind,
        ref=ref,
        dedupe_key=dedupe_key,
        payload=payload or {},
    )
    _processed_dedupe_keys.add(dedupe_key)
    _emitted_notifications.append(event)
    logger.info(
        "Notification emitted to user '%s': kind='%s', ref='%s', dedupe_key='%s'",
        clean_user,
        kind,
        ref,
        dedupe_key,
    )
    return True


def notify_group_members(
    group: Group,
    actor_id: Optional[uuid.UUID],
    kind: str,
    ref: str,
    payload: Optional[Dict[str, Any]] = None,
) -> List[NotificationEvent]:
    """Notify relevant group members after a committed transaction.

    Emits one notification per active member using a unique deduplication key.
    """
    from app.models.group import GroupMemberStatus

    emitted: List[NotificationEvent] = []
    active_members = [
        m for m in (group.members or []) if m.status == GroupMemberStatus.ACTIVE.value
    ]

    for member in active_members:
        dedupe_key = f"{kind}:{ref}:{member.user_id}"
        member_payload = dict(payload or {})
        member_payload["group_id"] = str(group.id)
        member_payload["actor_id"] = str(actor_id) if actor_id else None

        success = emit(
            user=member.user_id,
            kind=kind,
            ref=ref,
            dedupe_key=dedupe_key,
            payload=member_payload,
        )
        if success:
            emitted.append(_emitted_notifications[-1])

    return emitted
