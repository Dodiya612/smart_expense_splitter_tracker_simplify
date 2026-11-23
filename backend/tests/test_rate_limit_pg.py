"""Real-PostgreSQL tests for the shared rate limiter (T-39).

Verifies what the in-memory fake store cannot: the atomic ``INSERT ... ON CONFLICT DO UPDATE
... RETURNING`` under genuinely concurrent connections (the test engine uses NullPool, so every
operation runs on its own database connection), the real decrement / clear / purge SQL, the
CHECK constraint, end-to-end login limiting against real tables, the fail-closed 503, and
migration 012 (table, indexes, RLS and privilege lock-down, downgrade).

SKIPPED when no local PostgreSQL is reachable (localhost only, via COINSCIOUS_TEST_PG_URL, same
rules as tests/test_transaction_integrity_pg.py). It never touches Supabase.
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core import rate_limiter
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limiter import Policy, hash_identifier, hit, reserve
from app.core.rate_limiter import _store_clear as real_clear
from app.core.rate_limiter import _store_decrement as real_decrement
from app.core.rate_limiter import _store_increment as real_increment
from app.core.rate_limiter import _store_purge as real_purge
from app.core.security import hash_password
from app.main import app
from app.models.rate_limit import RateLimitBucket
from app.models.user import User
from tests import rate_limit_fakes as fakes
from tests.test_transaction_integrity_pg import pg  # noqa: F401 - fixture

POLICY = Policy(scope="pg_unit", limit=10, window_seconds=3600)
IP_HEADER = "X-Test-Client-IP"


@pytest.fixture
async def limiter(pg, monkeypatch) -> AsyncIterator[dict[str, Any]]:  # noqa: F811
    """Real SQL store on the throwaway database; clock frozen so a window cannot roll over."""
    fakes.reset()
    monkeypatch.setattr(rate_limiter, "_store_increment", real_increment)
    monkeypatch.setattr(rate_limiter, "_store_decrement", real_decrement)
    monkeypatch.setattr(rate_limiter, "_store_clear", real_clear)
    monkeypatch.setattr(rate_limiter, "_store_purge", real_purge)
    monkeypatch.setattr(rate_limiter, "_now", fakes.now)
    monkeypatch.setattr(rate_limiter, "AsyncSessionLocal", pg["sessions"])
    monkeypatch.setattr(settings, "RATE_LIMIT_PURGE_PROBABILITY", 0.0)
    yield pg
    fakes.reset()


async def rows(limiter: dict[str, Any]) -> list[RateLimitBucket]:
    async with limiter["sessions"]() as s:
        return list((await s.execute(select(RateLimitBucket))).scalars().all())


# ------------------------------------------------------------------------------
# Atomicity and concurrency on independent connections
# ------------------------------------------------------------------------------


async def test_concurrent_increments_never_lose_or_repeat_a_count(limiter):
    hits = await asyncio.gather(*[hit(POLICY, "same-key") for _ in range(60)])
    assert sorted(h.count for h in hits) == list(range(1, 61))  # each caller got a unique count
    (row,) = await rows(limiter)
    assert row.count == 60


async def test_concurrent_requests_cannot_exceed_the_limit(limiter):
    async def attempt() -> bool:
        try:
            await reserve([(POLICY, "burst")])
            return True
        except HTTPException as exc:
            assert exc.status_code == 429 and int(exc.headers["Retry-After"]) > 0
            return False

    results = await asyncio.gather(*[attempt() for _ in range(50)])
    assert sum(results) == POLICY.limit  # exactly the limit got through, never more
    assert len(results) - sum(results) == 40


async def test_concurrent_requests_for_different_keys_do_not_interfere(limiter):
    await asyncio.gather(*[hit(POLICY, f"user-{i % 5}") for i in range(50)])
    counts = sorted(r.count for r in await rows(limiter))
    assert counts == [10] * 5


async def test_only_hashes_are_stored_and_the_expiry_includes_a_grace_period(limiter):
    await hit(POLICY, "victim@example.com")
    (row,) = await rows(limiter)
    assert row.scope == "pg_unit"
    assert row.identifier_hash == hash_identifier("pg_unit", "victim@example.com")
    assert "victim" not in row.identifier_hash
    assert row.expires_at == row.window_start + timedelta(seconds=3600 + 60)


async def test_a_new_window_starts_a_new_counter(limiter):
    for _ in range(3):
        await hit(POLICY, "a")
    fakes.advance(3600)
    assert (await hit(POLICY, "a")).count == 1
    assert len(await rows(limiter)) == 2


async def test_database_rejects_a_negative_count(limiter):
    await hit(POLICY, "a")
    async with limiter["sessions"]() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("UPDATE rate_limit_buckets SET count = -1"))
            await s.commit()


# ------------------------------------------------------------------------------
# Refund, clear, purge (the real SQL)
# ------------------------------------------------------------------------------


async def test_refund_decrements_but_never_below_zero(limiter):
    hits = [await hit(POLICY, "a")]
    await rate_limiter.refund(hits)
    await rate_limiter.refund(hits)
    (row,) = await rows(limiter)
    assert row.count == 0


async def test_clear_removes_all_windows_of_one_counter_only(limiter):
    await hit(POLICY, "a")
    fakes.advance(3600)
    await hit(POLICY, "a")
    await hit(POLICY, "b")
    await rate_limiter.clear(POLICY, "a")
    remaining = await rows(limiter)
    assert [r.identifier_hash for r in remaining] == [hash_identifier("pg_unit", "b")]


async def test_purge_deletes_only_expired_rows_in_batches(limiter):
    for i in range(5):
        await hit(POLICY, f"old-{i}")
    fakes.advance(3600 + 61)  # past window end + grace
    await hit(POLICY, "fresh")
    assert await rate_limiter.purge_expired(batch=3) == 3
    assert await rate_limiter.purge_expired(batch=3) == 2
    assert await rate_limiter.purge_expired(batch=3) == 0
    (row,) = await rows(limiter)
    assert row.identifier_hash == hash_identifier("pg_unit", "fresh")


async def test_opportunistic_purge_runs_during_a_normal_request(limiter, monkeypatch):
    await hit(POLICY, "stale")
    fakes.advance(3600 + 61)
    monkeypatch.setattr(settings, "RATE_LIMIT_PURGE_PROBABILITY", 1.0)
    await reserve([(POLICY, "live")])
    assert [r.identifier_hash for r in await rows(limiter)] == [hash_identifier("pg_unit", "live")]


# ------------------------------------------------------------------------------
# End to end: real endpoints on real tables
# ------------------------------------------------------------------------------


@pytest.fixture
async def api(limiter, monkeypatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", IP_HEADER)

    async def override_get_db() -> AsyncIterator[Any]:
        async with limiter["sessions"]() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def add_user(limiter: dict[str, Any], email: str, password: str) -> User:
    user = User(id=uuid.uuid4(), email=email, name="Real User",
                hashed_password=hash_password(password), is_active=True)
    async with limiter["sessions"]() as s:
        s.add(user)
        await s.commit()
    return user


async def post_login(api: AsyncClient, email: str, password: str, ip: str):
    return await api.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers={IP_HEADER: ip}
    )


async def test_login_limits_use_the_real_tables_end_to_end(limiter, api):
    await add_user(limiter, "real@example.com", "RealPassword123!")
    for _ in range(5):
        assert (await post_login(api, "real@example.com", "wrong", "198.51.100.1")).status_code == 401
    blocked = await post_login(api, "real@example.com", "RealPassword123!", "198.51.100.1")
    assert blocked.status_code == 429
    assert blocked.json()["isRetryable"] is True and int(blocked.headers["retry-after"]) > 0
    # The legitimate owner at another address is not locked out by the attacker.
    ok = await post_login(api, "real@example.com", "RealPassword123!", "203.0.113.5")
    assert ok.status_code == 200
    stored = await rows(limiter)
    # The owner's successful login cleared the account-and-address and account-only buckets for the
    # account; the attacker's address bucket remains (a shared address-wide counter).
    assert {r.scope for r in stored} == {"login_pair", "login_ip"}
    assert not any(r.scope == "login_account" for r in stored)
    assert not any("real@example.com" in r.identifier_hash or "198.51" in r.identifier_hash for r in stored)


async def test_concurrent_login_guesses_cannot_exceed_the_per_address_limit(limiter, api):
    await add_user(limiter, "race@example.com", "RacePassword123!")
    responses = await asyncio.gather(
        *[post_login(api, "race@example.com", "wrong", "198.51.100.2") for _ in range(25)]
    )
    codes = [r.status_code for r in responses]
    assert codes.count(401) == 5 and codes.count(429) == 20  # five guesses, never more


async def test_a_successful_login_clears_the_counter_on_real_tables(limiter, api):
    await add_user(limiter, "clear@example.com", "ClearPassword123!")
    for _ in range(3):
        await post_login(api, "clear@example.com", "wrong", "198.51.100.3")
    assert (await post_login(api, "clear@example.com", "ClearPassword123!", "198.51.100.3")).status_code == 200
    scopes = {r.scope: r.count for r in await rows(limiter)}
    assert "login_pair" not in scopes and "login_account" not in scopes  # both cleared
    assert scopes["login_ip"] == 3  # address bucket kept: 3 failures, the success given back


async def test_login_fails_closed_with_503_when_the_database_is_unreachable(limiter, api, monkeypatch):
    await add_user(limiter, "down@example.com", "DownPassword123!")

    def unreachable() -> Any:
        raise ConnectionRefusedError("limiter database down")

    monkeypatch.setattr(rate_limiter, "AsyncSessionLocal", unreachable)
    response = await post_login(api, "down@example.com", "DownPassword123!", "198.51.100.4")
    assert response.status_code == 503
    assert response.json()["code"] == "RATE_LIMITER_UNAVAILABLE"
    assert "retry-after" not in response.headers


# ------------------------------------------------------------------------------
# Migration 012
# ------------------------------------------------------------------------------


def load_migration() -> Any:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "012_create_rate_limit_buckets.py"
    spec = importlib.util.spec_from_file_location("m012_pg", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_migration_012_creates_the_table_locks_it_down_and_downgrades(limiter):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = load_migration()
    async with limiter["admin"].connect() as admin:
        for role in ("anon", "authenticated"):
            exists = (await admin.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": role}
            )).scalar_one()
            if not exists:
                await admin.execute(text(f"CREATE ROLE {role} NOLOGIN"))

    def upgrade(sync_conn: Any) -> None:
        sync_conn.execute(text("DROP TABLE IF EXISTS rate_limit_buckets"))
        sync_conn.execute(text("GRANT USAGE ON SCHEMA public TO anon, authenticated"))
        # What Supabase does: new public tables are granted to the API roles by default.
        sync_conn.execute(text("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated"))
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.upgrade()

    def downgrade(sync_conn: Any) -> None:
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.downgrade()

    async with limiter["engine"].begin() as conn:
        await conn.run_sync(upgrade)
        rls = (await conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname='rate_limit_buckets'"))).scalar_one()
        policies = (await conn.execute(text("SELECT count(*) FROM pg_policies WHERE tablename='rate_limit_buckets'"))).scalar_one()
        assert rls is True and policies == 0
        for role in ("anon", "authenticated", "public"):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                granted = (await conn.execute(
                    text("SELECT has_table_privilege(:r, 'rate_limit_buckets', :p)"), {"r": role, "p": priv}
                )).scalar_one()
                assert granted is False, f"{role} still has {priv}"
        indexes = {r[0] for r in (await conn.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='rate_limit_buckets'"))).all()}
        assert {"pk_rate_limit_buckets", "ix_rate_limit_buckets_expires_at"} <= indexes
        await conn.run_sync(downgrade)
        gone = (await conn.execute(text("SELECT to_regclass('public.rate_limit_buckets')"))).scalar_one()
        assert gone is None
