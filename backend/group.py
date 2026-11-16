from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.settlement import Settlement
    from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(UTC)


class GroupType(str, Enum):
    FRIENDS = "friends"
    FLAT = "flat"
    TRIP = "trip"
    FAMILY = "family"


class GroupMemberRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


class GroupMemberStatus(str, Enum):
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint(
            "type IN ('friends', 'flat', 'trip', 'family')",
            name="ck_groups_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    creator: Mapped[User] = relationship(
        "User",
        foreign_keys=[created_by],
    )
    members: Mapped[list[GroupMember]] = relationship(
        "GroupMember",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    invitations: Mapped[list[GroupInvitation]] = relationship(
        "GroupInvitation",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    settlements: Mapped[list[Settlement]] = relationship(
        "Settlement",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'member')",
            name="ck_group_members_role_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'left', 'removed')",
            name="ck_group_members_status_valid",
        ),
        Index("ix_group_members_user_status", "user_id", "status"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        default=GroupMemberRole.MEMBER.value,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=GroupMemberStatus.ACTIVE.value,
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
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

    group: Mapped[Group] = relationship(
        "Group",
        back_populates="members",
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
    )


class GroupInvitation(Base):
    __tablename__ = "group_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="ck_group_invitations_status_valid",
        ),
        Index("ix_group_invitations_code_hash", "code_hash"),
        Index("ix_group_invitations_invited_user_status", "invited_user_id", "status"),
        Index("ix_group_invitations_group_status", "group_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    invited_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invited_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    invited_phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=InvitationStatus.PENDING.value,
        nullable=False,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    group: Mapped[Group] = relationship(
        "Group",
        back_populates="invitations",
    )
    invited_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[invited_user_id],
    )
    creator: Mapped[User] = relationship(
        "User",
        foreign_keys=[created_by],
    )

