"""Recurring expense models (US-14 / T-44). Mirrors alembic/versions/015_recurring_expenses.py.

``recurring_rules`` holds one schedule plus the expense template it creates.
``recurring_occurrences`` holds one row per (rule, occurrence date) the generator has
handled: either the expense it created or the reason it skipped that date. The UNIQUE
``(rule_id, occurrence_date)`` key is what guarantees an occurrence is handled at most
once, and the row is written in the same transaction as the expense it points to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base

FREQUENCIES: tuple[str, ...] = ("daily", "weekly", "monthly", "yearly")
RULE_STATUSES: tuple[str, ...] = ("active", "paused", "cancelled")
OCCURRENCE_STATUSES: tuple[str, ...] = ("created", "skipped")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class RecurringRule(Base):
    __tablename__ = "recurring_rules"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_recurring_rules_amount_positive"),
        CheckConstraint(f"frequency IN ({_in(FREQUENCIES)})", name="ck_recurring_rules_frequency_valid"),
        CheckConstraint(f"status IN ({_in(RULE_STATUSES)})", name="ck_recurring_rules_status_valid"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="ck_recurring_rules_end_after_start"
        ),
        CheckConstraint(
            "group_id IS NOT NULL OR split IS NULL", name="ck_recurring_rules_split_needs_group"
        ),
        Index("ix_recurring_rules_status_next_run", "status", "next_run_date"),
        Index("ix_recurring_rules_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    frequency: Mapped[str] = mapped_column(String(10), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The first date not yet handled; NULL when no occurrence remains (cancelled or ended).
    next_run_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")

    # Expense template.
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Group rules only: paid_by_user_id / payments / participant_user_ids / split_mode /
    # split_weights, exactly as accepted by SharedExpenseCreateRequest. Python None is stored
    # as SQL NULL (not JSON 'null'), as the ck_recurring_rules_split_needs_group CHECK expects.
    split: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecurringOccurrence(Base):
    __tablename__ = "recurring_occurrences"
    __table_args__ = (
        UniqueConstraint("rule_id", "occurrence_date", name="uq_recurring_occurrences_rule_date"),
        CheckConstraint(
            f"status IN ({_in(OCCURRENCE_STATUSES)})", name="ck_recurring_occurrences_status_valid"
        ),
        CheckConstraint(
            "(status = 'created' AND skip_reason IS NULL)"
            " OR (status = 'skipped' AND skip_reason IS NOT NULL AND expense_id IS NULL)",
            name="ck_recurring_occurrences_outcome",
        ),
        Index(
            "uq_recurring_occurrences_expense",
            "expense_id",
            unique=True,
            postgresql_where=text("expense_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recurring_rules.id", ondelete="CASCADE"), nullable=False
    )
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    # Checked at COMMIT (deferred) so the occurrence and the expense it points to can be
    # staged in either order inside their one transaction. A hard-deleted expense leaves
    # the row in place (SET NULL), so the date is never generated again.
    expense_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("expenses.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"),
        nullable=True,
    )
    skip_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
