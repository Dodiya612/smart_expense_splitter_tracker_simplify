"""create settlements table

Revision ID: 010_create_settlements
Revises: 009_create_shared_expenses_and_ledger
Create Date: 2026-11-16 23:45:00.000000

"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_create_settlements"
down_revision: str | None = "009_create_shared_expenses_and_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settlements",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("payer_id", sa.Uuid(), nullable=False),
        sa.Column("payee_id", sa.Uuid(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("payment_method", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("settlement_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount_paise > 0", name="ck_settlements_amount_positive"),
        sa.CheckConstraint("payer_id != payee_id", name="ck_settlements_payer_distinct"),
        sa.CheckConstraint("status IN ('completed', 'pending')", name="ck_settlements_status_valid"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payee_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_settlements_group_id"), "settlements", ["group_id"], unique=False)
    op.create_index(op.f("ix_settlements_payer_id"), "settlements", ["payer_id"], unique=False)
    op.create_index(op.f("ix_settlements_payee_id"), "settlements", ["payee_id"], unique=False)
    op.create_index("ix_settlements_group_created", "settlements", ["group_id", "created_at"], unique=False)
    op.create_index("ix_settlements_payer_payee", "settlements", ["payer_id", "payee_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_settlements_payer_payee", table_name="settlements")
    op.drop_index("ix_settlements_group_created", table_name="settlements")
    op.drop_index(op.f("ix_settlements_payee_id"), table_name="settlements")
    op.drop_index(op.f("ix_settlements_payer_id"), table_name="settlements")
    op.drop_index(op.f("ix_settlements_group_id"), table_name="settlements")
    op.drop_table("settlements")
