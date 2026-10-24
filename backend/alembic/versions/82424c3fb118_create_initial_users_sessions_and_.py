
"""Create initial users, sessions, and default categories."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "82424c3fb118"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    """Create the initial tables and insert default categories."""

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "currency",
            sa.Text(),
            server_default=sa.text("'INR'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )

    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_hash", sa.Text(), nullable=False),
        sa.Column("device_label", sa.Text(), nullable=True),
        sa.Column(
            "remember",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
    )

    op.create_index(
        "ix_sessions_user_id",
        "sessions",
        ["user_id"],
    )

    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(is_default AND owner_id IS NULL) "
            "OR (NOT is_default AND owner_id IS NOT NULL)",
            name="ck_categories_default_owner",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_categories_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
    )

    op.create_index(
        "uq_categories_default_name_lower",
        "categories",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("owner_id IS NULL AND is_default IS TRUE"),
    )

    op.create_index(
        "uq_categories_owner_name_lower",
        "categories",
        ["owner_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("owner_id IS NOT NULL AND is_default IS FALSE"),
    )

    categories_table = sa.table(
        "categories",
        sa.column("id", postgresql.UUID(as_uuid=False)),
        sa.column("owner_id", postgresql.UUID(as_uuid=False)),
        sa.column("name", sa.Text()),
        sa.column("is_default", sa.Boolean()),
    )

    op.bulk_insert(
        categories_table,
        [
            {
                "id": category_id,
                "owner_id": None,
                "name": category_name,
                "is_default": True,
            }
            for category_id, category_name in DEFAULT_CATEGORIES
        ],
    )


def downgrade() -> None:
    """Remove the initial schema and default categories."""

    op.drop_index(
        "uq_categories_owner_name_lower",
        table_name="categories",
    )
    op.drop_index(
        "uq_categories_default_name_lower",
        table_name="categories",
    )
    op.drop_table("categories")

    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
