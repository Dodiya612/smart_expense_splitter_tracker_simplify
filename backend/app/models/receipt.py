from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.expense import Expense
    from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(UTC)


class Receipt(Base):
    """Stores bill/receipt image metadata and optional database binary storage."""

    __tablename__ = "receipts"

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
    expense_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("expenses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    image_data: Mapped[bytes | None] = deferred(
        mapped_column(
            LargeBinary,
            nullable=True,
        )
    )
    content_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="image/jpeg",
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    expense: Mapped[Expense | None] = relationship("Expense", foreign_keys=[expense_id])

    __table_args__ = (
        CheckConstraint("file_size > 0 AND file_size < 1048576", name="ck_receipts_file_size_valid"),
        Index("ix_receipts_unlinked_created_at", "created_at", postgresql_where=(expense_id.is_(None))),
    )
