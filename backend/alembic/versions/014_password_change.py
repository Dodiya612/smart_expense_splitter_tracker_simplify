"""add users.token_version and the password_changed notification kind (T-50)

Revision ID: 014_password_change
Revises: 013_merge_rate_limit_and_receipts
Create Date: 2026-11-19 22:00:00.000000

Chained after T-46's merge revision 013_merge_rate_limit_and_receipts (which joins
012_create_rate_limit_buckets and 012_create_receipts), so the history keeps one head.
Neither T-46 migration touches the notification CHECK constraints or users.token_version.

What it changes
---------------
1. ``users.token_version`` INTEGER NOT NULL DEFAULT 0. Incremented by
   POST /api/v1/auth/change-password. Access tokens carry it as the ``tv`` claim and the
   backend rejects a token whose version is stale, so a password change ends every other
   device's access immediately. Existing rows get 0; access tokens issued before this
   deploy have no ``tv`` claim, which counts as 0, so nobody is signed out by the deploy.
2. Adds ``password_changed`` to the allowed ``kind`` values of ``notifications`` and
   ``notification_preferences`` (the CHECK constraints created by 011). It is a security
   notice: the application never lets a user switch it off.

No privileges or row level security settings are changed (011 and 012_create_rate_limit_buckets
already locked the notification tables down; ``users`` is untouched apart from the new column).

DEPLOY ORDER: apply this migration BEFORE deploying the T-50 code. The code reads
``users.token_version`` on every authenticated request and fails without the column.

Rollback (downgrade)
--------------------
Deletes every ``password_changed`` notification and preference row (the old CHECK
constraints would reject them), restores the 011 constraints and drops the column.
Roll the application code back FIRST: T-50 code running against the downgraded schema
fails on every authenticated request. After a downgrade, any access token that had been
invalidated by a password change becomes usable again until it expires (at most
ACCESS_TOKEN_EXPIRE_MINUTES); revoked refresh tokens stay revoked.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014_password_change"
down_revision: str | None = "013_merge_rate_limit_and_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
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
NEW_KINDS = OLD_KINDS + ("password_changed",)

CONSTRAINTS = (
    ("notifications", "ck_notifications_kind_valid"),
    ("notification_preferences", "ck_notification_preferences_kind_valid"),
)


def _kinds_sql(kinds: Sequence[str]) -> str:
    return ", ".join(f"'{kind}'" for kind in kinds)


def _replace_kind_constraints(kinds: Sequence[str]) -> None:
    for table, name in CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"kind IN ({_kinds_sql(kinds)})")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _replace_kind_constraints(NEW_KINDS)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE kind = 'password_changed'")
    op.execute("DELETE FROM notification_preferences WHERE kind = 'password_changed'")
    _replace_kind_constraints(OLD_KINDS)
    op.drop_column("users", "token_version")
