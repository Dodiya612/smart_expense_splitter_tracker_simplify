"""create auth tables

Revision ID: 001_create_auth_tables
Revises: None
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_create_auth_tables'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. Widen alembic_version.version_num (Alembic creates it as VARCHAR(32)).
    # Revision IDs from 004 onward are longer than 32 characters, so a fresh
    # `alembic upgrade head` fails at 004 without this. The version table
    # already exists when this first migration runs.
    op.alter_column(
        'alembic_version',
        'version_num',
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )

    # 1. Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # 2. Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('family_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('parent_id', sa.Uuid(), nullable=True),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['parent_id'], ['refresh_tokens.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_refresh_tokens_family_id'), 'refresh_tokens', ['family_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)


def downgrade() -> None:
    # 1. Drop refresh_tokens table and indexes
    op.drop_index(op.f('ix_refresh_tokens_expires_at'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_family_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')

    # 2. Drop users table and indexes
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

    # 3. Restore alembic_version.version_num to Alembic's default VARCHAR(32).
    # At this point the only stored value is '001_create_auth_tables', which fits.
    op.alter_column(
        'alembic_version',
        'version_num',
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
