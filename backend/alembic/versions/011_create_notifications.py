"""create notifications and notification_preferences tables

Revision ID: 011_create_notifications
Revises: 010_create_settlements
Create Date: 2026-11-19 10:00:00.000000

Access control (T-36 review fix)
--------------------------------
Both tables are read and written only by the FastAPI backend, which filters every
query by the authenticated user. They must NOT be reachable directly through
Supabase's auto-generated REST API (PostgREST) with the public anon key or a user's
access token. Supabase normally grants new tables in ``public`` to the ``anon`` and
``authenticated`` roles through default privileges, so this migration does not rely on
the absence of GRANT statements. For each table it:

1. ENABLEs row level security with NO policies. With RLS on and no policy, every role
   that is subject to RLS is denied all rows (default deny).
2. REVOKEs all privileges from PUBLIC, and from ``anon`` and ``authenticated`` when
   those roles exist (they do on Supabase, not on a plain local PostgreSQL).

The backend keeps working because it connects with the same DATABASE_URL that Alembic
uses to create these tables (alembic/env.py and app/core/database.py both read
settings.DATABASE_URL), so it is the table OWNER, and a table owner is exempt from RLS
unless FORCE ROW LEVEL SECURITY is set. FORCE is deliberately not used. Nothing is
revoked from the owner.

Not established from the repository (the project owner must verify before deploying):
whether the production DATABASE_URL role is the role that runs migrations. If the
application connects as a different role that neither owns these tables nor has
BYPASSRLS, it needs explicit GRANTs and RLS would block it. This migration also does
not change privileges on any other table, so it does not fix any exposure that
other tables may already have.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "011_create_notifications"
down_revision: str | None = "010_create_settlements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
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
)
KINDS_SQL = ", ".join(f"'{kind}'" for kind in KINDS)


def _lock_down(table: str) -> None:
    """Enable RLS (no policies) and remove Supabase API role access for one table."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        DECLARE api_role text;
        BEGIN
            FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
                    EXECUTE format('REVOKE ALL ON TABLE %I FROM %I', '{table}', api_role);
                END IF;
            END LOOP;
        END
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"kind IN ({KINDS_SQL})", name="ck_notifications_kind_valid"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe_key"),
    )
    op.create_index(
        "ix_notifications_user_created",
        "notifications",
        ["user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("read_at IS NULL"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(f"kind IN ({KINDS_SQL})", name="ck_notification_preferences_kind_valid"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "kind"),
    )

    _lock_down("notifications")
    _lock_down("notification_preferences")


def downgrade() -> None:
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_user_unread", table_name="notifications")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
