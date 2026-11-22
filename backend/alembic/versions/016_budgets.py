"""create budgets and budget_alerts; add budget notification kinds (T-48)

Revision ID: 016_budgets
Revises: 015_recurring_expenses
Create Date: 2026-11-21 12:00:00.000000

What it changes
---------------
1. ``budgets``: one spending limit per user (``limit_paise`` > 0), weekly or monthly,
   overall (``category_id`` NULL) or for one category. Soft-deleted with ``deleted_at``.
   Two partial UNIQUE indexes allow at most one ACTIVE budget per (user, period) overall
   and per (user, period, category).
2. ``budget_alerts``: one row per (budget, period start, threshold) reached.
   UNIQUE (budget_id, period_start, threshold) guarantees the 80% and 100% alerts are
   each recorded at most once per period, even under concurrent saves. ``suppressed``
   marks an 80% row stored together with the 100% row (never announced).
3. Adds ``budget_warning`` and ``budget_exceeded`` to the allowed ``kind`` values of
   ``notifications`` and ``notification_preferences``.

Row level security
------------------
Like the other tables, the new ones are reached only through the backend's own role;
no grants or policies are changed here.

Rollback (downgrade)
--------------------
Deletes notification and preference rows of the two new kinds (the 015 CHECK
constraints would reject them), restores the 015 constraints and drops both tables
(budgets and their alert history are lost). Roll the application code back FIRST:
T-48 code reads these tables after every expense save.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016_budgets"
down_revision: str | None = "015_recurring_expenses"
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
    "password_changed",
    "recurring_expense_upcoming",
    "recurring_expense_skipped",
)
ADDED_KINDS = ("budget_warning", "budget_exceeded")
NEW_KINDS = OLD_KINDS + ADDED_KINDS

CONSTRAINTS = (
    ("notifications", "ck_notifications_kind_valid"),
    ("notification_preferences", "ck_notification_preferences_kind_valid"),
)


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _replace_kind_constraints(kinds: Sequence[str]) -> None:
    for table, name in CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"kind IN ({_in(kinds)})")


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column(
            "category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True
        ),
        sa.Column("limit_paise", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("limit_paise > 0", name="ck_budgets_limit_positive"),
        sa.CheckConstraint("period IN ('weekly', 'monthly')", name="ck_budgets_period_valid"),
    )
    op.create_index(
        "uq_budgets_active_overall",
        "budgets",
        ["user_id", "period"],
        unique=True,
        postgresql_where=sa.text("category_id IS NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_budgets_active_category",
        "budgets",
        ["user_id", "period", "category_id"],
        unique=True,
        postgresql_where=sa.text("category_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index("ix_budgets_user_created", "budgets", ["user_id", "created_at"])

    op.create_table(
        "budget_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("budget_id", sa.Uuid(), sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("threshold", sa.SmallInteger(), nullable=False),
        sa.Column("spent_paise", sa.BigInteger(), nullable=False),
        sa.Column("limit_paise", sa.BigInteger(), nullable=False),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "budget_id", "period_start", "threshold", name="uq_budget_alerts_budget_period_threshold"
        ),
        sa.CheckConstraint("threshold IN (80, 100)", name="ck_budget_alerts_threshold_valid"),
        sa.CheckConstraint("period_end >= period_start", name="ck_budget_alerts_period_order"),
        sa.CheckConstraint("spent_paise >= 0", name="ck_budget_alerts_spent_non_negative"),
        sa.CheckConstraint("limit_paise > 0", name="ck_budget_alerts_limit_positive"),
    )

    _replace_kind_constraints(NEW_KINDS)


def downgrade() -> None:
    op.execute(f"DELETE FROM notifications WHERE kind IN ({_in(ADDED_KINDS)})")
    op.execute(f"DELETE FROM notification_preferences WHERE kind IN ({_in(ADDED_KINDS)})")
    _replace_kind_constraints(OLD_KINDS)
    op.drop_table("budget_alerts")
    op.drop_index("ix_budgets_user_created", table_name="budgets")
    op.drop_index("uq_budgets_active_category", table_name="budgets")
    op.drop_index("uq_budgets_active_overall", table_name="budgets")
    op.drop_table("budgets")
