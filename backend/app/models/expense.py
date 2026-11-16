from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.group import Group
    from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(UTC)


class Expense(Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_expenses_amount_positive"),
        Index("ix_expenses_user_deleted_date", "user_id", "deleted_at", "expense_date"),
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
        index=True,
    )
    group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount_minor: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    expense_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    merchant: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    payment_mode: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,
    )

    user: Mapped[User] = relationship("User", lazy="selectin", foreign_keys=[user_id])
    group: Mapped[Optional[Group]] = relationship("Group", lazy="selectin", foreign_keys=[group_id])
    category: Mapped[Category] = relationship("Category", lazy="selectin", foreign_keys=[category_id])
    payments: Mapped[List[ExpensePayment]] = relationship(
        "ExpensePayment",
        back_populates="expense",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    shares: Mapped[List[ExpenseShare]] = relationship(
        "ExpenseShare",
        back_populates="expense",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ExpensePayment(Base):
    __tablename__ = "expense_payments"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_expense_payments_amount_positive"),
    )

    expense_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("expenses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    amount_paise: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    expense: Mapped[Expense] = relationship("Expense", back_populates="payments")
    user: Mapped[User] = relationship("User", lazy="selectin")


class ExpenseShare(Base):
    __tablename__ = "expense_shares"
    __table_args__ = (
        CheckConstraint("amount_paise >= 0", name="ck_expense_shares_amount_non_negative"),
    )

    expense_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("expenses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    amount_paise: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    rule: Mapped[str] = mapped_column(
        String(50),
        default="equal",
        nullable=False,
    )
    rule_value: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )

    expense: Mapped[Expense] = relationship("Expense", back_populates="shares")
    user: Mapped[User] = relationship("User", lazy="selectin")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    before_after: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    actor: Mapped[Optional[User]] = relationship("User", lazy="selectin")
