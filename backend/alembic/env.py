
"""Alembic migration environment for Coinscious."""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from alembic import context
from app.core.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def get_database_url() -> str:
    """Read the database URL from the application's settings."""
    database_url = settings.DIRECT_URL or settings.DATABASE_URL

    if not database_url:
        raise RuntimeError(
            "Database URL is not configured. Set DIRECT_URL or DATABASE_URL."
        )

    url = make_url(database_url)

    if url.drivername in {"postgresql", "postgres"}:
        url = url.set(drivername="postgresql+psycopg")

    return url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Generate SQL without connecting to the database."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a database connection."""
    connectable = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
