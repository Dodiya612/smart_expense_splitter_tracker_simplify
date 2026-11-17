"""create groups, group_members, and group_invitations tables

Revision ID: 008_create_groups_and_members
Revises: 007_add_pg_trgm_and_search_indexes
Create Date: 2026-11-16 22:00:00.000000

"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_create_groups_and_members"
down_revision: str | None = "007_pg_trgm_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create groups table
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("type IN ('friends', 'flat', 'trip', 'family')", name="ck_groups_type_valid"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_groups_created_by"), "groups", ["created_by"], unique=False)

    # 2. Create group_members table
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="member", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_group_members_role_valid"),
        sa.CheckConstraint("status IN ('active', 'left', 'removed')", name="ck_group_members_status_valid"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_group_members_user_status", "group_members", ["user_id", "status"], unique=False)

    # 3. Create group_invitations table
    op.create_table(
        "group_invitations",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
        sa.Column("invited_user_id", sa.Uuid(), nullable=True),
        sa.Column("invited_email", sa.String(length=255), nullable=True),
        sa.Column("invited_phone", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="ck_group_invitations_status_valid",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_group_invitations_code_hash", "group_invitations", ["code_hash"], unique=False)
    op.create_index("ix_group_invitations_group_status", "group_invitations", ["group_id", "status"], unique=False)
    op.create_index("ix_group_invitations_invited_user_status", "group_invitations", ["invited_user_id", "status"], unique=False)
    op.create_index(op.f("ix_group_invitations_invited_email"), "group_invitations", ["invited_email"], unique=False)


def downgrade() -> None:
    op.drop_table("group_invitations")
    op.drop_table("group_members")
    op.drop_table("groups")

