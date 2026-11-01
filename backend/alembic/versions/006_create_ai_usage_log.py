"""create ai_usage_log table

Revision ID: 006_create_ai_usage_log
Revises: 005_create_category_suggestion_feedback
Create Date: 2026-11-01 15:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '006_create_ai_usage_log'
down_revision: str | None = '005_create_category_suggestion_feedback'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'ai_usage_log',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('feature', sa.String(length=50), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_ai_usage_log_user_id'),
        'ai_usage_log',
        ['user_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ai_usage_log_feature'),
        'ai_usage_log',
        ['feature'],
        unique=False,
    )
    op.create_index(
        op.f('ix_ai_usage_log_created_at'),
        'ai_usage_log',
        ['created_at'],
        unique=False,
    )
    op.create_index(
        'ix_ai_usage_log_user_feature_created',
        'ai_usage_log',
        ['user_id', 'feature', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_ai_usage_log_user_feature_created',
        table_name='ai_usage_log',
    )
    op.drop_index(
        op.f('ix_ai_usage_log_created_at'),
        table_name='ai_usage_log',
    )
    op.drop_index(
        op.f('ix_ai_usage_log_feature'),
        table_name='ai_usage_log',
    )
    op.drop_index(
        op.f('ix_ai_usage_log_user_id'),
        table_name='ai_usage_log',
    )
    op.drop_table('ai_usage_log')
