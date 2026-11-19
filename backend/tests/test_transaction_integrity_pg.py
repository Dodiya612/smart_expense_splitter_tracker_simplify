"""Real-PostgreSQL check for T-38's Done-when (US-34):
"Killing the connection mid-save leaves nothing half-written."

Each test creates a throwaway database, builds the schema from the models, starts a
multi-row save through the real service code (shared expense: expense + payments +
shares + audit event; settlement: settlement + audit event + idempotency record),
flushes every row to the server inside the open transaction, then kills that
connection from a second connection with pg_terminate_backend() just before COMMIT.
Afterwards a fresh connection must find none of those rows. The database is dropped
at the end.

The whole module is SKIPPED when no local PostgreSQL is reachable.
Set COINSCIOUS_TEST_PG_URL to an admin URL on a LOCAL server, for example
    postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
(default: that URL). Only localhost / 127.0.0.1 / ::1 are accepted, so this can
never touch Supabase or any shared database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.core.database import Base
from app.models.category import Category
from app.models.expense import AuditEvent, Expense, ExpensePayment, ExpenseShare
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus, GroupType
from app.models.idempotency import IdempotencyRecord
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.settlement import SettlementCreateRequest
from app.schemas.shared_expense import SharedExpenseCreateRequest
from app.services import settlement_service, shared_expense_service

DEFAULT_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
ADMIN_URL = os.getenv("COINSCIOUS_TEST_PG_URL", DEFAULT_ADMIN_URL)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


async def _admin_engine_or_skip() -> AsyncEngine:
    url = make_url(ADMIN_URL)
    if url.host not in LOCAL_HOSTS:
        pytest.skip(f"COINSCIOUS_TEST_PG_URL must point at a local server, got host '{url.host}'.")
    engine = create_async_engine(
        url, poolclass=NullPool, isolation_level="AUTOCOMMIT", connect_args={"timeout": 3}
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any connection problem means "no Postgres here"
        await engine.dispose()
        pytest.skip(
            "No local PostgreSQL reachable at "
            f"{url.render_as_string(hide_password=True)} ({type(exc).__name__}); "
            "Done-when not verified on a real database. Set COINSCIOUS_TEST_PG_URL to run."
        )
    return engine


@pytest.fixture
async def pg() -> AsyncIterator[dict[str, Any]]:
    """Throwaway database with the full schema; dropped afterwards."""
    admin = await _admin_engine_or_skip()
    db_name = f"coinscious_t38_{uuid.uuid4().hex[:12]}"
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    url = make_url(ADMIN_URL).set(database=db_name)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield {"admin": admin, "engine": engine, "sessions": async_sessionmaker(engine, expire_on_commit=False)}
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d AND pid <> pg_backend_pid()"),
                {"d": db_name},
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        await admin.dispose()


async def seed(sessions: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    now = datetime.now(UTC)
    users = [
        User(id=uuid.uuid4(), email=f"{n}@example.com", name=n.title(), hashed_password="x", is_active=True)
        for n in ("alex", "blair", "casey")
    ]
    cat = Category(id=uuid.uuid4(), name="Groceries", is_default=True)
    grp = Group(id=uuid.uuid4(), name="Flat Expenses", type=GroupType.FLAT.value,
                created_by=users[0].id, created_at=now, updated_at=now)
    async with sessions() as s:
        s.add_all(users + [cat, grp])
        await s.flush()
        for i, u in enumerate(users):
            s.add(GroupMember(
                group_id=grp.id, user_id=u.id,
                role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
                status=GroupMemberStatus.ACTIVE.value, joined_at=now, updated_at=now,
            ))
        await s.commit()
    return {"users": users, "category": cat, "group": grp}


def kill_connection_before_commit(session: AsyncSession, admin: AsyncEngine, seen: dict[str, Any]) -> None:
    """Replace session.commit: flush every row, kill this connection, then try to commit."""
    real_commit = session.commit

    async def commit_after_kill() -> None:
        await session.flush()  # every INSERT has now reached the server, inside the transaction
        pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        seen["pid"] = pid
        async with admin.connect() as conn:
            killed = (await conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})).scalar_one()
        seen["killed"] = killed
        await real_commit()

    session.commit = commit_after_kill  # type: ignore[method-assign]


async def count(sessions: async_sessionmaker[AsyncSession], stmt: Any) -> int:
    async with sessions() as s:
        return int((await s.execute(stmt)).scalar_one())


async def test_shared_expense_create_killed_mid_transaction_writes_nothing(pg):
    world = await seed(pg["sessions"])
    alex = world["users"][0]
    payload = SharedExpenseCreateRequest(
        amount_paise=300000, description="Killed groceries", category_id=world["category"].id
    )
    seen: dict[str, Any] = {}
    async with pg["sessions"]() as s:
        kill_connection_before_commit(s, pg["admin"], seen)
        with pytest.raises(SQLAlchemyError):
            await shared_expense_service.create_shared_expense(s, world["group"].id, alex, payload)
    assert seen.get("killed") is True, "the save never reached the kill point"

    sessions = pg["sessions"]
    assert await count(sessions, select(func.count()).select_from(Expense)) == 0
    assert await count(sessions, select(func.count()).select_from(ExpensePayment)) == 0
    assert await count(sessions, select(func.count()).select_from(ExpenseShare)) == 0
    assert await count(sessions, select(func.count()).select_from(AuditEvent)) == 0


async def test_shared_expense_with_key_killed_then_same_key_retry_creates_one(pg):
    world = await seed(pg["sessions"])
    alex = world["users"][0]
    payload = SharedExpenseCreateRequest(
        amount_paise=300000, description="Groceries with key", category_id=world["category"].id
    )
    key = "killed-expense-1"
    sessions = pg["sessions"]

    seen: dict[str, Any] = {}
    async with sessions() as s:
        kill_connection_before_commit(s, pg["admin"], seen)
        with pytest.raises(SQLAlchemyError):
            await shared_expense_service.create_shared_expense(
                s, world["group"].id, alex, payload, idempotency_key=key
            )
    assert seen.get("killed") is True, "the save never reached the kill point"
    assert await count(sessions, select(func.count()).select_from(Expense)) == 0
    assert await count(sessions, select(func.count()).select_from(ExpenseShare)) == 0
    assert await count(sessions, select(func.count()).select_from(IdempotencyRecord)) == 0

    # The retry with the same key on a healthy connection creates exactly one expense...
    async with sessions() as s:
        created, replay = await shared_expense_service.create_shared_expense(
            s, world["group"].id, alex, payload, idempotency_key=key
        )
    assert replay is False
    # ...and a second retry replays it instead of creating another.
    async with sessions() as s:
        again, replay_again = await shared_expense_service.create_shared_expense(
            s, world["group"].id, alex, payload, idempotency_key=key
        )
    assert replay_again is True
    assert again.id == created.id
    assert await count(sessions, select(func.count()).select_from(Expense)) == 1
    assert await count(sessions, select(func.count()).select_from(ExpenseShare)) == 3
    assert await count(sessions, select(func.count()).select_from(IdempotencyRecord)) == 1


async def test_settlement_create_killed_mid_transaction_writes_nothing(pg):
    world = await seed(pg["sessions"])
    alex, blair, _ = world["users"]
    async with pg["sessions"]() as s:
        await shared_expense_service.create_shared_expense(
            s, world["group"].id, alex,
            SharedExpenseCreateRequest(amount_paise=300000, description="Groceries", category_id=world["category"].id),
        )
    sessions = pg["sessions"]
    audits_before = await count(sessions, select(func.count()).select_from(AuditEvent))

    seen: dict[str, Any] = {}
    async with sessions() as s:
        kill_connection_before_commit(s, pg["admin"], seen)
        with pytest.raises(SQLAlchemyError):
            await settlement_service.create_settlement(
                s, world["group"].id, blair,
                SettlementCreateRequest(payer_id=blair.id, payee_id=alex.id, amount_paise=100000),
                idempotency_key="killed-settlement-1",
            )
    assert seen.get("killed") is True, "the save never reached the kill point"

    assert await count(sessions, select(func.count()).select_from(Settlement)) == 0
    assert await count(sessions, select(func.count()).select_from(IdempotencyRecord)) == 0
    assert await count(sessions, select(func.count()).select_from(AuditEvent)) == audits_before

    # And the retry with the same key on a healthy connection creates exactly one.
    async with sessions() as s:
        result, replay = await settlement_service.create_settlement(
            s, world["group"].id, blair,
            SettlementCreateRequest(payer_id=blair.id, payee_id=alex.id, amount_paise=100000),
            idempotency_key="killed-settlement-1",
        )
    assert replay is False
    assert result.amount_paise == 100000
    assert await count(sessions, select(func.count()).select_from(Settlement)) == 1
