"""create expenses, categories, and idempotency_records tables

Revision ID: 004_create_expenses_and_categories
Revises: 003_add_session_fields
Create Date: 2026-10-30 15:00:00.000000

"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '004_create_expenses_and_categories'
down_revision: str | None = '003_add_session_fields'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DEFAULT_CATEGORIES = [
    ("00000000-0000-4000-8000-000000000001", "Food & Dining"),
    ("00000000-0000-4000-8000-000000000002", "Groceries"),
    ("00000000-0000-4000-8000-000000000003", "Travel & Transport"),
    ("00000000-0000-4000-8000-000000000004", "Shopping"),
    ("00000000-0000-4000-8000-000000000005", "Bills & Utilities"),
    ("00000000-0000-4000-8000-000000000006", "Rent & Housing"),
    ("00000000-0000-4000-8000-000000000007", "Entertainment"),
    ("00000000-0000-4000-8000-000000000008", "Health"),
    ("00000000-0000-4000-8000-000000000009", "Education"),
    ("00000000-0000-4000-8000-000000000010", "Personal Care"),
    ("00000000-0000-4000-8000-000000000011", "Gifts & Donations"),
    ("00000000-0000-4000-8000-000000000012", "Other"),
]


def upgrade() -> None:
    # 1. Create categories table
    op.create_table(
        'categories',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('owner_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_categories_owner_id'), 'categories', ['owner_id'], unique=False)

    # Seed default categories
    categories_table = sa.table(
        'categories',
        sa.column('id', sa.Uuid()),
        sa.column('owner_id', sa.Uuid()),
        sa.column('name', sa.String()),
        sa.column('is_default', sa.Boolean()),
    )
    op.bulk_insert(
        categories_table,
        [
            {
                "id": uuid.UUID(cat_id),
                "owner_id": None,
                "name": cat_name,
                "is_default": True,
            }
            for cat_id, cat_name in DEFAULT_CATEGORIES
        ],
    )

    # 2. Create expenses table
    op.create_table(
        'expenses',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('category_id', sa.Uuid(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('expense_date', sa.Date(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('merchant', sa.String(length=255), nullable=True),
        sa.Column('payment_mode', sa.String(length=50), nullable=True),
        sa.Column('receipt_id', sa.Uuid(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('amount_minor > 0', name='ck_expenses_amount_positive'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_expenses_category_id'), 'expenses', ['category_id'], unique=False)
    op.create_index(op.f('ix_expenses_deleted_at'), 'expenses', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_expenses_expense_date'), 'expenses', ['expense_date'], unique=False)
    op.create_index(op.f('ix_expenses_user_id'), 'expenses', ['user_id'], unique=False)
    op.create_index('ix_expenses_user_deleted_date', 'expenses', ['user_id', 'deleted_at', 'expense_date'], unique=False)

    # 3. Create idempotency_records table
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=False),
        sa.Column('response_body', sa.Text(), nullable=False),
        sa.Column('resource_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'key', name='uq_idempotency_records_user_key'),
    )
    op.create_index(op.f('ix_idempotency_records_user_id'), 'idempotency_records', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_idempotency_records_user_id'), table_name='idempotency_records')
    op.drop_table('idempotency_records')

    op.drop_index('ix_expenses_user_deleted_date', table_name='expenses')
    op.drop_index(op.f('ix_expenses_user_id'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_expense_date'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_deleted_at'), table_name='expenses')
    op.drop_index(op.f('ix_expenses_category_id'), table_name='expenses')
    op.drop_table('expenses')

    op.drop_index(op.f('ix_categories_owner_id'), table_name='categories')
    op.drop_table('categories')
