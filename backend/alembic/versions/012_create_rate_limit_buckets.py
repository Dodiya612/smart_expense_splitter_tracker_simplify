"""create rate_limit_buckets table (T-39)

Revision ID: 012_create_rate_limit_buckets
Revises: 011_create_notifications
Create Date: 2026-11-19 18:00:00.000000

Shared, database-backed fixed-window rate-limit counters. One row per
(scope, hashed identifier, window start); the application increments a row with a
single atomic ``INSERT ... ON CONFLICT DO UPDATE ... RETURNING count`` so concurrent
requests on any worker or instance cannot exceed a limit. Identifiers (emails, user
ids, client addresses) are stored only as keyed hashes. Expired rows are removed by
the application (see app/core/rate_limiter.py: purge_expired).

DEPLOY ORDER: apply this migration BEFORE deploying code that uses it. Every
limited route fails closed (HTTP 503) when the counters are unavailable, so the
code must not run against a database that does not have this table yet.

Access control: like 011, this table is only used by the FastAPI backend and must NOT
be reachable through Supabase's auto-generated REST API. Row level security is
enabled with no policies, and privileges are revoked from PUBLIC and, when those roles
exist (they do on Supabase, not on plain PostgreSQL), from ``anon`` and
``authenticated``. The backend connects with the same DATABASE_URL that Alembic uses,
so it owns the table and is exempt from RLS (FORCE ROW LEVEL SECURITY is deliberately
not used). This migration changes nothing on any other table.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_create_rate_limit_buckets"
down_revision: str | None = "011_create_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
        "rate_limit_buckets",
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("count >= 0", name="ck_rate_limit_buckets_count_non_negative"),
        sa.PrimaryKeyConstraint("scope", "identifier_hash", "window_start", name="pk_rate_limit_buckets"),
    )
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"], unique=False)
    _lock_down("rate_limit_buckets")


def downgrade() -> None:
    op.drop_index("ix_rate_limit_buckets_expires_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
