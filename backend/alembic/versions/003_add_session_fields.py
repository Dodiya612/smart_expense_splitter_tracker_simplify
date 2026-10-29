"""add session fields to refresh_tokens

Revision ID: 003_add_session_fields
Revises: 002_create_login_rate_limits
Create Date: 2026-10-29 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "003_add_session_fields"
down_revision: Union[str, None] = "002_create_login_rate_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("refresh_tokens")}

    if "device_label" not in existing_columns:
        op.add_column(
            "refresh_tokens",
            sa.Column("device_label", sa.String(length=150), nullable=True),
        )

    if "remember" not in existing_columns:
        op.add_column(
            "refresh_tokens",
            sa.Column("remember", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )

    if "last_seen" not in existing_columns:
        op.add_column(
            "refresh_tokens",
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("refresh_tokens")}

    if "last_seen" in existing_columns:
        op.drop_column("refresh_tokens", "last_seen")

    if "remember" in existing_columns:
        op.drop_column("refresh_tokens", "remember")

    if "device_label" in existing_columns:
        op.drop_column("refresh_tokens", "device_label")
