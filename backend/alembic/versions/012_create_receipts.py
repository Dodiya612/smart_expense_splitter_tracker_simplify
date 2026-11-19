"""create receipts table

Revision ID: 012_create_receipts
Revises: 011_create_notifications
Create Date: 2026-11-19 21:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '012_create_receipts'
down_revision: str | None = '011_create_notifications'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'receipts',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('expense_id', sa.Uuid(), nullable=True),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('image_data', sa.LargeBinary(), nullable=True),
        sa.Column('content_type', sa.String(length=50), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint('file_size > 0 AND file_size < 1048576', name='ck_receipts_file_size_valid'),
        sa.ForeignKeyConstraint(['expense_id'], ['expenses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('storage_key', name='uq_receipts_storage_key'),
    )
    op.create_index(
        op.f('ix_receipts_user_id'),
        'receipts',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_receipts_expense_id'),
        'receipts',
        ['expense_id'],
        unique=False,
    )
    op.create_index(
        'ix_receipts_unlinked_created_at',
        'receipts',
        ['created_at'],
        unique=False,
        postgresql_where=sa.text('expense_id IS NULL'),
    )


def downgrade() -> None:
    op.drop_index(
        'ix_receipts_unlinked_created_at',
        table_name='receipts',
        postgresql_where=sa.text('expense_id IS NULL'),
    )
    op.drop_index(
        op.f('ix_receipts_expense_id'),
        table_name='receipts',
    )
    op.drop_index(
        op.f('ix_receipts_user_id'),
        table_name='receipts',
    )
    op.drop_table('receipts')
