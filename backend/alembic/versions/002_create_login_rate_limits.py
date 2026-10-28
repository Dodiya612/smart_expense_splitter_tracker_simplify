"""create login_rate_limits table

Revision ID: 002_create_login_rate_limits
Revises: 001_create_auth_tables
Create Date: 2026-10-28 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_create_login_rate_limits'
down_revision: Union[str, None] = '001_create_auth_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'login_rate_limits' not in tables:
        # Fresh database: create table with defaults and unique index
        op.create_table(
            'login_rate_limits',
            sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
            sa.Column('key', sa.String(length=255), nullable=False),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default=sa.text('1')),
            sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_login_rate_limits_key'), 'login_rate_limits', ['key'], unique=True)
    else:
        # Existing database: safely reconcile indexes and unique constraints without data loss
        existing_indexes = {ix['name']: ix for ix in inspector.get_indexes('login_rate_limits')}
        existing_constraints = {c['name']: c for c in inspector.get_unique_constraints('login_rate_limits')}

        # Drop non-unique index if it was previously created
        if 'ix_login_rate_limits_key' in existing_indexes and not existing_indexes['ix_login_rate_limits_key']['unique']:
            op.drop_index('ix_login_rate_limits_key', table_name='login_rate_limits')

        # Drop redundant table-level unique constraint if present
        if 'login_rate_limits_key_key' in existing_constraints:
            op.drop_constraint('login_rate_limits_key_key', table_name='login_rate_limits', type_='unique')

        # Ensure canonical unique index 'ix_login_rate_limits_key' exists
        refreshed_indexes = {ix['name'] for ix in sa.inspect(bind).get_indexes('login_rate_limits')}
        if 'ix_login_rate_limits_key' not in refreshed_indexes:
            op.create_index(op.f('ix_login_rate_limits_key'), 'login_rate_limits', ['key'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'login_rate_limits' in tables:
        existing_indexes = {ix['name'] for ix in inspector.get_indexes('login_rate_limits')}
        if 'ix_login_rate_limits_key' in existing_indexes:
            op.drop_index(op.f('ix_login_rate_limits_key'), table_name='login_rate_limits')
        op.drop_table('login_rate_limits')
