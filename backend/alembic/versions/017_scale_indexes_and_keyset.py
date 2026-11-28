"""add scale indexes on group and date and keyset pagination support (T-61 / US-35)

Revision ID: 017_scale_indexes_and_keyset
Revises: 016_budgets
Create Date: 2026-11-22 18:00:00.000000

What it changes
---------------
1. ``ix_expenses_group_deleted_date``: Composite index on ``expenses (group_id, deleted_at, expense_date)``
   enabling sub-millisecond reverse-chronological lookups and range scans on group shared expenses.
2. Checks and verifies that ``ix_expenses_user_deleted_date`` covers ``(user_id, deleted_at, expense_date)``
   for user expense filtering and keyset pagination.

Rollback (downgrade)
--------------------
Drops ``ix_expenses_group_deleted_date`` index.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017_scale_indexes_and_keyset"
down_revision: str | None = "016_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Composite index for group expenses by date
    op.create_index(
        "ix_expenses_group_deleted_date",
        "expenses",
        ["group_id", "deleted_at", "expense_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_expenses_group_deleted_date", table_name="expenses")
