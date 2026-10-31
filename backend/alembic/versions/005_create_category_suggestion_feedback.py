"""create category_suggestion_feedback table

Revision ID: 005_create_category_suggestion_feedback
Revises: 004_create_expenses_and_categories
Create Date: 2026-10-31 17:50:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '005_create_category_suggestion_feedback'
down_revision: str | None = '004_create_expenses_and_categories'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'category_suggestion_feedback',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=False),
        sa.Column('merchant', sa.String(length=200), nullable=True),
        sa.Column('suggested_category_id', sa.Uuid(), nullable=False),
        sa.Column('chosen_category_id', sa.Uuid(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('accepted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['chosen_category_id'], ['categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['suggested_category_id'], ['categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_category_suggestion_feedback_user_id'),
        'category_suggestion_feedback',
        ['user_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_category_suggestion_feedback_user_id'),
        table_name='category_suggestion_feedback',
    )
    op.drop_table('category_suggestion_feedback')

