"""Notification models (US-38 / T-36).

``notifications`` holds one row per (user, event). The unique ``(user_id, dedupe_key)``
constraint is what guarantees the same event never notifies the same user twice,
even under concurrent requests or retries.

``notification_preferences`` holds only explicit choices; a missing row means the
notification type is enabled.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base

# Every kind maps to a real operation in the app. Keep in sync with the CHECK
# constraints created by alembic/versions/011_create_notifications.py (and updated by 014_password_change.py).
NOTIFICATION_KINDS: tuple[str, ...] = (
    "group_expense_created",
    "group_expense_updated",
    "group_expense_deleted",
    "settlement_recorded",
    "member_joined",
    "invitation_received",
    "invitation_accepted",
    "invitation_declined",
    "member_removed",
    "member_left",
    # T-50: account security notice. Added by alembic/versions/014_password_change.py.
    "password_changed",
)

# Kinds a user may never switch off; the preference API and emit() both honour this set.
SECURITY_KINDS: frozenset[str] = frozenset({"password_changed"})


def utcnow() -> datetime:
    return datetime.now(UTC)


def _kinds_sql() -> str:
    return ", ".join(f"'{kind}'" for kind in NOTIFICATION_KINDS)


class Notification(Base):
    """Mirrors alembic/versions/011_create_notifications.py."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe_key"),
        CheckConstraint(f"kind IN ({_kinds_sql()})", name="ck_notifications_kind_valid"),
        Index("ix_notifications_user_created", "user_id", desc("created_at"), desc("id")),
        Index(
            "ix_notifications_user_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )


class NotificationPreference(Base):
    """Mirrors alembic/versions/011_create_notifications.py."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ({_kinds_sql()})", name="ck_notification_preferences_kind_valid"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    kind: Mapped[str] = mapped_column(String(50), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
