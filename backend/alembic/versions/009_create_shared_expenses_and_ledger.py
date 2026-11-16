"""create shared expenses, expense payments, expense shares, and audit events

Revision ID: 009_create_shared_expenses_and_ledger
Revises: 008_create_groups_and_members
Create Date: 2026-11-16 22:30:00.000000

"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_create_shared_expenses_and_ledger"
down_revision: str | None = "008_create_groups_and_members"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add group_id to expenses table
    op.add_column("expenses", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_expenses_group_id",
        "expenses",
        "groups",
        ["group_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_expenses_group_id"), "expenses", ["group_id"], unique=False)

    # 2. Create expense_payments table
    op.create_table(
        "expense_payments",
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("amount_paise > 0", name="ck_expense_payments_amount_positive"),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("expense_id", "user_id"),
    )
    op.create_index(op.f("ix_expense_payments_user_id"), "expense_payments", ["user_id"], unique=False)

    # 3. Create expense_shares table
    op.create_table(
        "expense_shares",
        sa.Column("expense_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("rule", sa.String(length=50), nullable=False, server_default="equal"),
        sa.Column("rule_value", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.CheckConstraint("amount_paise >= 0", name="ck_expense_shares_amount_non_negative"),
        sa.ForeignKeyConstraint(["expense_id"], ["expenses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("expense_id", "user_id"),
    )
    op.create_index(op.f("ix_expense_shares_user_id"), "expense_shares", ["user_id"], unique=False)

    # 4. Create audit_events table
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("before_after", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_events_actor_id"), "audit_events", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_events_entity_id"), "audit_events", ["entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_entity_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index(op.f("ix_expense_shares_user_id"), table_name="expense_shares")
    op.drop_table("expense_shares")

    op.drop_index(op.f("ix_expense_payments_user_id"), table_name="expense_payments")
    op.drop_table("expense_payments")

    op.drop_index(op.f("ix_expenses_group_id"), table_name="expenses")
    op.drop_constraint("fk_expenses_group_id", "expenses", type_="foreignkey")
    op.drop_column("expenses", "group_id")
