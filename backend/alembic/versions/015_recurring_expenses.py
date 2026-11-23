"""create recurring_rules and recurring_occurrences; add recurring notification kinds (T-44)

Revision ID: 015_recurring_expenses
Revises: 014_password_change
Create Date: 2026-11-20 12:00:00.000000

What it changes
---------------
1. ``recurring_rules``: one schedule (frequency, start/end date, next run date, status)
   plus the expense template it creates (amount_paise, category, description, optional
   notes/merchant/payment mode, and for group rules the split as JSON).
   CHECKs: amount_paise > 0, frequency and status allowlists, end_date >= start_date,
   a split only on group rules.
2. ``recurring_occurrences``: one row per (rule, occurrence date) the generator handled.
   UNIQUE (rule_id, occurrence_date) guarantees each occurrence is created at most once;
   the row is inserted in the same transaction as the expense it points to. The
   expense foreign key is DEFERRABLE INITIALLY DEFERRED (checked at COMMIT) and
   ON DELETE SET NULL (a deleted expense is never generated again).
3. Adds ``recurring_expense_upcoming`` and ``recurring_expense_skipped`` to the allowed
   ``kind`` values of ``notifications`` and ``notification_preferences``.

Row level security
------------------
Like the other tables, the new ones are reached only through the backend's own role;
no grants or policies are changed here.

Rollback (downgrade)
--------------------
Deletes notification and preference rows of the two new kinds (the 014 CHECK
constraints would reject them), restores the 014 constraints and drops both tables.
Expenses already generated stay as ordinary expenses. Roll the application code back
FIRST: T-44 code reads these tables on login and in the hourly task.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "015_recurring_expenses"
down_revision: str | None = "014_password_change"
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
)
ADDED_KINDS = ("recurring_expense_upcoming", "recurring_expense_skipped")
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
        "recurring_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=True),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("next_run_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'active'")),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column(
            "category_id", sa.Uuid(), sa.ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("merchant", sa.String(255), nullable=True),
        sa.Column("payment_mode", sa.String(50), nullable=True),
        sa.Column("split", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_paise > 0", name="ck_recurring_rules_amount_positive"),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly', 'yearly')",
            name="ck_recurring_rules_frequency_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'cancelled')", name="ck_recurring_rules_status_valid"
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="ck_recurring_rules_end_after_start"
        ),
        sa.CheckConstraint(
            "group_id IS NOT NULL OR split IS NULL", name="ck_recurring_rules_split_needs_group"
        ),
    )
    op.create_index("ix_recurring_rules_status_next_run", "recurring_rules", ["status", "next_run_date"])
    op.create_index("ix_recurring_rules_owner_created", "recurring_rules", ["owner_id", "created_at"])
    op.create_index("ix_recurring_rules_group_id", "recurring_rules", ["group_id"])

    op.create_table(
        "recurring_occurrences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "rule_id", sa.Uuid(), sa.ForeignKey("recurring_rules.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("occurrence_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "expense_id",
            sa.Uuid(),
            sa.ForeignKey("expenses.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"),
            nullable=True,
        ),
        sa.Column("skip_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("rule_id", "occurrence_date", name="uq_recurring_occurrences_rule_date"),
        sa.CheckConstraint(
            "status IN ('created', 'skipped')", name="ck_recurring_occurrences_status_valid"
        ),
        sa.CheckConstraint(
            "(status = 'created' AND skip_reason IS NULL)"
            " OR (status = 'skipped' AND skip_reason IS NOT NULL AND expense_id IS NULL)",
            name="ck_recurring_occurrences_outcome",
        ),
    )
    op.create_index(
        "uq_recurring_occurrences_expense",
        "recurring_occurrences",
        ["expense_id"],
        unique=True,
        postgresql_where=sa.text("expense_id IS NOT NULL"),
    )

    _replace_kind_constraints(NEW_KINDS)


def downgrade() -> None:
    op.execute(f"DELETE FROM notifications WHERE kind IN ({_in(ADDED_KINDS)})")
    op.execute(f"DELETE FROM notification_preferences WHERE kind IN ({_in(ADDED_KINDS)})")
    _replace_kind_constraints(OLD_KINDS)
    op.drop_index("uq_recurring_occurrences_expense", table_name="recurring_occurrences")
    op.drop_table("recurring_occurrences")
    op.drop_index("ix_recurring_rules_group_id", table_name="recurring_rules")
    op.drop_index("ix_recurring_rules_owner_created", table_name="recurring_rules")
    op.drop_index("ix_recurring_rules_status_next_run", table_name="recurring_rules")
    op.drop_table("recurring_rules")
