"""Budget models (US-25 / T-48). Mirrors alembic/versions/016_budgets.py.

``budgets`` holds one spending limit per user: weekly or monthly, overall (no category)
or for one category. A deleted budget keeps its row (``deleted_at`` set) so its alert
history stays readable; at most one ACTIVE budget exists per (user, period, category or
overall), enforced by two partial unique indexes.

``budget_alerts`` holds one row per (budget, period, threshold) that was reached. The
UNIQUE ``(budget_id, period_start, threshold)`` key is what guarantees each threshold
alerts at most once per period, even under concurrent saves.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

BUDGET_PERIODS: tuple[str, ...] = ("weekly", "monthly")
#: Percent of the limit at which an alert is recorded, lowest first.
ALERT_THRESHOLDS: tuple[int, ...] = (80, 100)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("limit_paise > 0", name="ck_budgets_limit_positive"),
        CheckConstraint(f"period IN ({_in(BUDGET_PERIODS)})", name="ck_budgets_period_valid"),
        Index(
            "uq_budgets_active_overall",
            "user_id",
            "period",
            unique=True,
            postgresql_where=text("category_id IS NULL AND deleted_at IS NULL"),
        ),
        Index(
            "uq_budgets_active_category",
            "user_id",
            "period",
            "category_id",
            unique=True,
            postgresql_where=text("category_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_budgets_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
    )
    limit_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"
    __table_args__ = (
        UniqueConstraint(
            "budget_id", "period_start", "threshold", name="uq_budget_alerts_budget_period_threshold"
        ),
        CheckConstraint("threshold IN (80, 100)", name="ck_budget_alerts_threshold_valid"),
        CheckConstraint("period_end >= period_start", name="ck_budget_alerts_period_order"),
        CheckConstraint("spent_paise >= 0", name="ck_budget_alerts_spent_non_negative"),
        CheckConstraint("limit_paise > 0", name="ck_budget_alerts_limit_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    threshold: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    spent_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    limit_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: True for an 80% row recorded together with the 100% row (spending jumped straight
    #: past 100%): it blocks a later 80% alert in the period and was never announced.
    suppressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
