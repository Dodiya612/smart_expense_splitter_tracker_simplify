"""add pg_trgm extension and trigram search indexes to expenses

Revision ID: 007_add_pg_trgm_and_search_indexes
Revises: 006_create_ai_usage_log
Create Date: 2026-11-04 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_add_pg_trgm_and_search_indexes"
down_revision: str | None = "006_create_ai_usage_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enable pg_trgm extension (PostgreSQL specific)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # 2. Create GIN Trigram indexes on searchable text columns in expenses
    op.create_index(
        "ix_expenses_description_trgm",
        "expenses",
        ["description"],
        postgresql_using="gin",
        postgresql_ops={"description": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_expenses_notes_trgm",
        "expenses",
        ["notes"],
        postgresql_using="gin",
        postgresql_ops={"notes": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_expenses_merchant_trgm",
        "expenses",
        ["merchant"],
        postgresql_using="gin",
        postgresql_ops={"merchant": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_expenses_merchant_trgm", table_name="expenses")
    op.drop_index("ix_expenses_notes_trgm", table_name="expenses")
    op.drop_index("ix_expenses_description_trgm", table_name="expenses")
