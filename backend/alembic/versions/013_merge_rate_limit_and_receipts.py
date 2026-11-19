"""merge rate_limit_buckets and receipts heads

Revision ID: 013_merge_rate_limit_and_receipts
Revises: 012_create_rate_limit_buckets, 012_create_receipts
Create Date: 2026-11-19 23:20:00.000000

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "013_merge_rate_limit_and_receipts"
down_revision: tuple[str, ...] | str | None = (
    "012_create_rate_limit_buckets",
    "012_create_receipts",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass