"""Real-PostgreSQL checks of the analytics API (US-12 / T-42).

The schema is built by the real Alembic migrations (``alembic upgrade head``), not by
``Base.metadata.create_all``: once per module into a template database, which every
test then copies (``CREATE DATABASE ... TEMPLATE``) so each test starts from an empty,
fully migrated schema. Expenses, settlements, edits and deletes go through the real
endpoints and services; the figures come from the real aggregate SQL (UNION ALL legs,
SUM over BIGINT paise, date_trunc, Monday weeks).

Covered: the PRODUCT.md section 05 demo exact to the paisa for Alex, Blair and Casey
(summary and categories) and its agreement with ``ledger.allocate``; day, week and
month buckets with running totals and empty buckets; settlements, soft-deleted
expenses and other users' data never counted; edits visible at once (no cache); the
group filter (member, past member, stranger, unknown group); range validation and
authentication.

The whole module is SKIPPED when no local PostgreSQL is reachable (localhost only,
never Supabase; same COINSCIOUS_TEST_PG_URL setting as
tests/test_transaction_integrity_pg.py). All databases are dropped afterwards.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import Expense, ExpenseShare
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus, GroupType
from app.models.user import User
from app.schemas.settlement import SettlementCreateRequest
from app.schemas.shared_expense import SharedExpenseCreateRequest
from app.services import analytics_service, settlement_service, shared_expense_service
from app.services.ledger import allocate
from tests import test_transaction_integrity_pg as pg_support

T = TypeVar("T")

GROCERIES = uuid.UUID("00000000-0000-4000-8000-000000000002")
TRAVEL = uuid.UUID("00000000-0000-4000-8000-000000000003")
FOOD = uuid.UUID("00000000-0000-4000-8000-000000000001")
MONDAY = date(2026, 11, 16)
START = date(2026, 11, 1)
END = date(2026, 11, 30)
NOVEMBER = {"from": "2026-11-01", "to": "2026-11-30"}
ENDPOINTS = ("summary", "trends", "categories")


# ==============================================================================
# Throwaway databases built by Alembic
# ==============================================================================


def _url(database: str) -> URL:
    return make_url(pg_support.ADMIN_URL).set(database=database)


def _in_worker_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run fn in a fresh thread, so its own asyncio.run() never touches the test loop."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn, *args).result()


async def _admin_execute(*statements: str, terminate: str | None = None) -> None:
    admin = await pg_support._admin_engine_or_skip()  # skips the module without PostgreSQL
    try:
        async with admin.connect() as conn:
            if terminate is not None:
                await conn.execute(
                    text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                         "WHERE datname = :d AND pid <> pg_backend_pid()"),
                    {"d": terminate},
                )
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await admin.dispose()


def _migrate_to_head(database: str) -> None:
    # No ini file: alembic/env.py then leaves the test run's logging configuration alone.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with pytest.MonkeyPatch.context() as mp:  # env.py reads settings.DATABASE_URL
        mp.setattr(settings, "DATABASE_URL", _url(database).render_as_string(hide_password=False))
        command.upgrade(cfg, "head")


@pytest.fixture(scope="module")
def migrated_template() -> Iterator[str]:
    """A database migrated with ``alembic upgrade head``, used as a template; dropped afterwards."""
    name = f"coinscious_t42_{uuid.uuid4().hex[:12]}"
    _in_worker_thread(asyncio.run, _admin_execute(f'CREATE DATABASE "{name}"'))
    try:
        _in_worker_thread(_migrate_to_head, name)
        yield name
    finally:
        _in_worker_thread(asyncio.run, _admin_execute(f'DROP DATABASE IF EXISTS "{name}"', terminate=name))


@pytest.fixture
async def pg(migrated_template: str) -> AsyncIterator[dict[str, Any]]:
    """A fresh copy of the migrated schema for one test; dropped afterwards."""
    name = f"{migrated_template}_{uuid.uuid4().hex[:8]}"
    await _admin_execute(f'CREATE DATABASE "{name}" TEMPLATE "{migrated_template}"')
    engine = create_async_engine(_url(name), poolclass=NullPool)
    try:
        yield {"engine": engine, "sessions": async_sessionmaker(engine, expire_on_commit=False)}
    finally:
        await engine.dispose()
        await _admin_execute(f'DROP DATABASE IF EXISTS "{name}"', terminate=name)


@pytest.fixture
async def api(pg: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    """The real app, with every request on a real session of the throwaway database."""
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with pg["sessions"]() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


# ==============================================================================
# Seed data and helpers
# ==============================================================================


async def seed_demo(sessions: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Alex, Blair and Casey in one group, in that fixed order; Sam is a stranger."""
    now = datetime.now(UTC)
    users = [
        User(id=uuid.uuid4(), email=f"{n}@example.com", name=n.title(), hashed_password="x", is_active=True)
        for n in ("alex", "blair", "casey", "sam")
    ]
    grp = Group(id=uuid.uuid4(), name="Flat Expenses", type=GroupType.FLAT.value,
                created_by=users[0].id, created_at=now, updated_at=now)
    sams_group = Group(id=uuid.uuid4(), name="Sam's Trip", type=GroupType.TRIP.value,
                       created_by=users[3].id, created_at=now, updated_at=now)
    async with sessions() as s:
        # The default categories come from migration 004, not from the test.
        seeded = (await s.execute(
            select(Category.id, Category.name).where(Category.id.in_((GROCERIES, TRAVEL, FOOD)))
        )).all()
        assert sorted(seeded) == [(FOOD, "Food & Dining"), (GROCERIES, "Groceries"), (TRAVEL, "Travel & Transport")]
        s.add_all([*users, grp, sams_group])
        await s.flush()
        for i, u in enumerate(users[:3]):  # fixed order: Alex first, so Alex gets the extra paisa
            s.add(GroupMember(
                group_id=grp.id, user_id=u.id,
                role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
                status=GroupMemberStatus.ACTIVE.value, joined_at=now + timedelta(seconds=i), updated_at=now,
            ))
        s.add(GroupMember(group_id=sams_group.id, user_id=users[3].id, role=GroupMemberRole.ADMIN.value,
                          status=GroupMemberStatus.ACTIVE.value, joined_at=now, updated_at=now))
        await s.commit()
    return {"alex": users[0], "blair": users[1], "casey": users[2], "sam": users[3],
            "group": grp, "sams_group": sams_group}


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, email=user.email)}"}


async def add_personal(api: AsyncClient, user: User, amount: int, category: uuid.UUID, day: date) -> dict[str, Any]:
    resp = await api.post(
        "/api/v1/expenses",
        json={"amount_paise": amount, "description": "Personal", "category_id": str(category),
              "expense_date": day.isoformat()},
        headers=bearer(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def add_shared(api: AsyncClient, group: Group, payer: User, amount: int, category: uuid.UUID,
                     day: date) -> dict[str, Any]:
    resp = await api.post(
        f"/api/v1/groups/{group.id}/expenses",
        json={"amount_paise": amount, "description": "Shared", "category_id": str(category),
              "split_mode": "equal", "expense_date": day.isoformat()},
        headers=bearer(payer),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def settle(api: AsyncClient, group: Group, payer: User, payee: User, amount: int) -> None:
    resp = await api.post(
        f"/api/v1/groups/{group.id}/settlements",
        json={"payer_id": str(payer.id), "payee_id": str(payee.id), "amount_paise": amount},
        headers=bearer(payer),
    )
    assert resp.status_code == 201, resp.text


async def get(api: AsyncClient, path: str, user: User, **params: str) -> dict[str, Any]:
    resp = await api.get(f"/api/v1/analytics/{path}", params=params, headers=bearer(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def figures(api: AsyncClient, user: User, **params: str) -> tuple[int, int, int, int]:
    """(share, cash paid, owed to you, you owe) for November 2026."""
    s = await get(api, "summary", user, **NOVEMBER, **params)
    return s["share_paise"], s["cash_paid_paise"], s["owed_to_you_paise"], s["you_owe_paise"]


async def by_category(api: AsyncClient, user: User, **params: str) -> list[tuple[str, int, int, int]]:
    body = await get(api, "categories", user, **NOVEMBER, **params)
    rows = [(c["category_name"], c["share_paise"], c["cash_paid_paise"], c["expense_count"])
            for c in body["categories"]]
    assert body["total_share_paise"] == sum(r[1] for r in rows)
    assert body["total_cash_paid_paise"] == sum(r[2] for r in rows)
    return rows


def buckets(body: dict[str, Any]) -> list[tuple[str, str, int, int, int, int]]:
    return [(b["bucket_start"], b["bucket_end"], b["share_paise"], b["cash_paid_paise"],
             b["cumulative_share_paise"], b["cumulative_cash_paid_paise"]) for b in body["buckets"]]


# ==============================================================================
# Demo dataset (PRODUCT.md section 05), exact to the paisa
# ==============================================================================


async def test_demo_dataset_on_real_postgres(pg):
    """The same demo through the services directly (no HTTP)."""
    sessions = pg["sessions"]
    w = await seed_demo(sessions)
    alex, blair, casey, group = w["alex"], w["blair"], w["casey"], w["group"]

    async def service_figures(user: User) -> tuple[int, int, int, int]:
        async with sessions() as s:
            r = await analytics_service.get_summary(s, user, START, END)
        return r.share_paise, r.cash_paid_paise, r.owed_to_you_paise, r.you_owe_paise

    async with sessions() as s:  # 1. Alex pays ₹3,000 groceries, split by three
        await shared_expense_service.create_shared_expense(
            s, group.id, alex,
            SharedExpenseCreateRequest(amount_paise=300000, description="Groceries",
                                       category_id=GROCERIES, expense_date=MONDAY),
        )
    assert await service_figures(alex) == (100000, 300000, 200000, 0)

    async with sessions() as s:  # 2. Blair repays Alex ₹1,000
        await settlement_service.create_settlement(
            s, group.id, blair, SettlementCreateRequest(payer_id=blair.id, payee_id=alex.id, amount_paise=100000)
        )
    assert await service_figures(alex) == (100000, 300000, 100000, 0)
    assert await service_figures(blair) == (100000, 0, 0, 0)

    async with sessions() as s:  # 3. Alex adds a personal ₹500 metro recharge
        now = datetime.now(UTC)
        s.add(Expense(id=uuid.uuid4(), user_id=alex.id, group_id=None, category_id=TRAVEL, amount_minor=50000,
                      description="Metro recharge", expense_date=MONDAY + timedelta(days=1),
                      version=1, created_at=now, updated_at=now))
        # A deleted expense never counts.
        s.add(Expense(id=uuid.uuid4(), user_id=alex.id, group_id=None, category_id=TRAVEL, amount_minor=99900,
                      description="Deleted", expense_date=MONDAY, version=2, created_at=now,
                      updated_at=now, deleted_at=now))
        await s.commit()
    assert await service_figures(alex) == (150000, 350000, 100000, 0)

    async with sessions() as s:  # 4. Casey pays ₹100 chai, split by three
        await shared_expense_service.create_shared_expense(
            s, group.id, casey,
            SharedExpenseCreateRequest(amount_paise=10000, description="Chai",
                                       category_id=FOOD, expense_date=MONDAY + timedelta(days=2)),
        )
    assert await service_figures(alex) == (153334, 350000, 96666, 0)
    assert await service_figures(blair) == (103333, 0, 0, 3333)
    assert await service_figures(casey) == (103333, 10000, 0, 93333)

    async with sessions() as s:
        cats = await analytics_service.get_categories(s, alex, START, END)
        weeks = await analytics_service.get_trends(
            s, alex, "week", from_date=date(2026, 11, 9), to_date=date(2026, 11, 22)
        )
        days = await analytics_service.get_trends(
            s, alex, "day", from_date=MONDAY - timedelta(days=1), to_date=MONDAY + timedelta(days=3)
        )
        grouped = await analytics_service.get_summary(s, alex, START, END, group_id=group.id)

    assert [(c.category_name, c.share_paise, c.cash_paid_paise) for c in cats.categories] == [
        ("Groceries", 100000, 300000),
        ("Travel & Transport", 50000, 50000),
        ("Food & Dining", 3334, 0),
    ]
    assert [(b.bucket_start, b.share_paise) for b in weeks.buckets] == [
        (date(2026, 11, 9), 0),
        (date(2026, 11, 16), 153334),  # date_trunc('week') starts on Monday
    ]
    assert [b.cumulative_share_paise for b in days.buckets] == [0, 100000, 150000, 153334, 153334]
    assert (grouped.share_paise, grouped.cash_paid_paise) == (103334, 300000)  # personal excluded


async def test_demo_dataset_step_by_step_through_the_api(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, blair, casey, group = w["alex"], w["blair"], w["casey"], w["group"]

    # 1. Alex pays ₹3,000 groceries split equally by three.
    groceries = await add_shared(api, group, alex, 300000, GROCERIES, MONDAY)
    assert await figures(api, alex) == (100000, 300000, 200000, 0)
    assert await figures(api, blair) == (100000, 0, 0, 100000)
    assert await figures(api, casey) == (100000, 0, 0, 100000)

    # 2. Blair repays Alex ₹1,000: a settlement changes balances, never share or cash paid.
    await settle(api, group, blair, alex, 100000)
    assert await figures(api, alex) == (100000, 300000, 100000, 0)
    assert await figures(api, blair) == (100000, 0, 0, 0)
    assert await figures(api, casey) == (100000, 0, 0, 100000)

    # 3. Alex adds a personal ₹500 metro recharge.
    await add_personal(api, alex, 50000, TRAVEL, MONDAY + timedelta(days=1))
    assert await figures(api, alex) == (150000, 350000, 100000, 0)
    assert await figures(api, blair) == (100000, 0, 0, 0)
    assert await figures(api, casey) == (100000, 0, 0, 100000)

    # 4. Casey pays ₹100 chai split by three: 3334 / 3333 / 3333, the extra paisa to Alex.
    chai = await add_shared(api, group, casey, 10000, FOOD, MONDAY + timedelta(days=2))
    assert await figures(api, alex) == (153334, 350000, 96666, 0)
    assert await figures(api, blair) == (103333, 0, 0, 3333)
    assert await figures(api, casey) == (103333, 10000, 0, 93333)

    assert (await get(api, "summary", alex, **NOVEMBER))["expense_count"] == 3
    assert (await get(api, "summary", blair, **NOVEMBER))["expense_count"] == 2
    assert (await get(api, "summary", casey, **NOVEMBER))["expense_count"] == 2

    assert await by_category(api, alex) == [
        ("Groceries", 100000, 300000, 1),
        ("Travel & Transport", 50000, 50000, 1),
        ("Food & Dining", 3334, 0, 1),
    ]
    assert await by_category(api, blair) == [("Groceries", 100000, 0, 1), ("Food & Dining", 3333, 0, 1)]
    assert await by_category(api, casey) == [("Groceries", 100000, 0, 1), ("Food & Dining", 3333, 10000, 1)]

    # The stored shares, and so the analytics figures, are exactly what ledger.allocate() gives.
    order = [str(alex.id), str(blair.id), str(casey.id)]
    expected = {
        uuid.UUID(groceries["id"]): allocate(300000, order, "equal"),
        uuid.UUID(chai["id"]): allocate(10000, order, "equal"),
    }
    assert expected[uuid.UUID(chai["id"])] == {order[0]: 3334, order[1]: 3333, order[2]: 3333}
    async with pg["sessions"]() as s:
        stored = (await s.execute(select(ExpenseShare))).scalars().all()
    assert {(r.expense_id, str(r.user_id)): r.amount_paise for r in stored} == {
        (eid, uid): amount for eid, shares in expected.items() for uid, amount in shares.items()
    }
    for user in (alex, blair, casey):
        shared_share = sum(shares[str(user.id)] for shares in expected.values())
        personal = 50000 if user is alex else 0
        assert (await figures(api, user))[0] == shared_share + personal


# ==============================================================================
# Buckets: day, week (Monday–Sunday), month; running totals; empty buckets
# ==============================================================================


async def test_adjacent_dates_land_on_their_own_day_and_week(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, group = w["alex"], w["group"]
    sunday, monday = date(2026, 11, 15), date(2026, 11, 16)
    await add_personal(api, alex, 1100, FOOD, sunday)
    await add_shared(api, group, alex, 3000, FOOD, monday)  # share 1000, cash 3000

    days = await get(api, "trends", alex, granularity="day", **{"from": "2026-11-14", "to": "2026-11-17"})
    assert buckets(days) == [
        ("2026-11-14", "2026-11-14", 0, 0, 0, 0),
        ("2026-11-15", "2026-11-15", 1100, 1100, 1100, 1100),
        ("2026-11-16", "2026-11-16", 1000, 3000, 2100, 4100),
        ("2026-11-17", "2026-11-17", 0, 0, 2100, 4100),
    ]
    weeks = await get(api, "trends", alex, granularity="week", **{"from": "2026-11-09", "to": "2026-11-22"})
    assert buckets(weeks) == [
        ("2026-11-09", "2026-11-15", 1100, 1100, 1100, 1100),  # Sunday closes the week
        ("2026-11-16", "2026-11-22", 1000, 3000, 2100, 4100),  # Monday opens the next one
    ]
    assert (weeks["total_share_paise"], weeks["total_cash_paid_paise"]) == (2100, 4100)

    # The buckets come from the stored Asia/Kolkata calendar date: whatever the
    # PostgreSQL session time zone is, nothing shifts to another day.
    for zone in ("UTC", "Pacific/Honolulu", "Pacific/Kiritimati"):
        async with pg["sessions"]() as s:
            await s.execute(text(f"SET TIME ZONE '{zone}'"))
            r = await analytics_service.get_trends(s, alex, "day", date(2026, 11, 14), date(2026, 11, 17))
        assert [(b.bucket_start.isoformat(), b.share_paise) for b in r.buckets] == [
            ("2026-11-14", 0), ("2026-11-15", 1100), ("2026-11-16", 1000), ("2026-11-17", 0)
        ], zone


async def test_default_range_is_this_month_to_today_in_kolkata(pg, api, monkeypatch):
    """00:30 IST on 20 Nov is still 19 Nov in UTC: the default range must end on the 20th."""
    w = await seed_demo(pg["sessions"])
    alex = w["alex"]
    after_midnight_utc = datetime(2026, 11, 19, 19, 0, tzinfo=UTC)  # 00:30 IST, 20 Nov
    await add_personal(api, alex, 1100, FOOD, date(2026, 11, 19))
    await add_personal(api, alex, 2200, FOOD, date(2026, 11, 20))
    await add_personal(api, alex, 4400, FOOD, date(2026, 10, 31))  # last month: outside the default

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return after_midnight_utc.astimezone(tz) if tz else after_midnight_utc.replace(tzinfo=None)

    monkeypatch.setattr(settlement_service, "datetime", FrozenDateTime)
    body = await get(api, "trends", alex)
    assert (body["from_date"], body["to_date"], body["timezone"]) == ("2026-11-01", "2026-11-20", "Asia/Kolkata")
    assert len(body["buckets"]) == 20
    assert {b["bucket_start"]: b["share_paise"] for b in body["buckets"]}["2026-11-20"] == 2200
    assert body["total_share_paise"] == 3300
    summary = await get(api, "summary", alex)
    assert (summary["from_date"], summary["to_date"], summary["share_paise"]) == ("2026-11-01", "2026-11-20", 3300)


async def test_week_and_month_buckets_with_running_totals_and_empty_buckets(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, group = w["alex"], w["group"]
    await add_personal(api, alex, 9000, FOOD, date(2026, 10, 26))   # Monday, before 'from' below
    await add_personal(api, alex, 1000, FOOD, date(2026, 10, 31))   # Saturday
    await add_personal(api, alex, 2000, TRAVEL, date(2026, 11, 1))  # Sunday
    await add_personal(api, alex, 4000, FOOD, date(2026, 11, 2))    # Monday
    await add_shared(api, group, alex, 24000, GROCERIES, date(2026, 11, 18))  # share 8000, cash 24000

    weeks = await get(api, "trends", alex, granularity="week", **{"from": "2026-10-28", "to": "2026-11-22"})
    assert buckets(weeks) == [
        ("2026-10-26", "2026-11-01", 3000, 3000, 3000, 3000),  # 26 Oct is before 'from': not counted
        ("2026-11-02", "2026-11-08", 4000, 4000, 7000, 7000),
        ("2026-11-09", "2026-11-15", 0, 0, 7000, 7000),       # empty week
        ("2026-11-16", "2026-11-22", 8000, 24000, 15000, 31000),
    ]
    assert all(date.fromisoformat(b[0]).weekday() == 0 for b in buckets(weeks))
    assert all(date.fromisoformat(b[1]).weekday() == 6 for b in buckets(weeks))

    months = await get(api, "trends", alex, granularity="month", **{"from": "2026-09-01", "to": "2026-11-30"})
    assert buckets(months) == [
        ("2026-09-01", "2026-09-30", 0, 0, 0, 0),              # empty month
        ("2026-10-01", "2026-10-31", 10000, 10000, 10000, 10000),
        ("2026-11-01", "2026-11-30", 14000, 30000, 24000, 40000),
    ]
    assert (months["total_share_paise"], months["total_cash_paid_paise"]) == (24000, 40000)

    days = await get(api, "trends", alex, granularity="day", **{"from": "2026-10-31", "to": "2026-11-04"})
    assert [(b[0], b[2], b[4]) for b in buckets(days)] == [
        ("2026-10-31", 1000, 1000),
        ("2026-11-01", 2000, 3000),  # month boundary between adjacent days
        ("2026-11-02", 4000, 7000),
        ("2026-11-03", 0, 7000),
        ("2026-11-04", 0, 7000),
    ]


# ==============================================================================
# What never counts, and whose data
# ==============================================================================


async def test_settlements_deleted_expenses_and_other_users_are_excluded(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, blair, sam, group = w["alex"], w["blair"], w["sam"], w["group"]
    await add_shared(api, group, alex, 300000, GROCERIES, MONDAY)
    await settle(api, group, blair, alex, 60000)  # two partial settlements: Blair still owes 10000
    await settle(api, group, blair, alex, 30000)

    # Soft-deleted through the real endpoints: a shared and a personal expense.
    gone_shared = await add_shared(api, group, alex, 90000, FOOD, MONDAY)
    resp = await api.delete(f"/api/v1/groups/{group.id}/expenses/{gone_shared['id']}",
                            params={"version": gone_shared["version"]}, headers=bearer(alex))
    assert resp.status_code in (200, 204), resp.text
    gone_personal = await add_personal(api, alex, 77700, TRAVEL, MONDAY)
    resp = await api.delete(f"/api/v1/expenses/{gone_personal['id']}", headers=bearer(alex))
    assert resp.status_code in (200, 204), resp.text
    async with pg["sessions"]() as s:
        deleted = (await s.execute(select(Expense).where(Expense.deleted_at.is_not(None)))).scalars().all()
    assert len(deleted) == 2  # the rows are still there, only marked deleted

    # Sam (a stranger) has their own personal and group spending.
    await add_personal(api, sam, 12300, FOOD, MONDAY)
    await add_shared(api, w["sams_group"], sam, 45600, TRAVEL, MONDAY)

    assert await figures(api, alex) == (100000, 300000, 110000, 0)  # Blair 10000 + Casey 100000
    assert await figures(api, blair) == (100000, 0, 0, 10000)
    assert await figures(api, sam) == (12300 + 45600, 12300 + 45600, 0, 0)
    assert (await get(api, "summary", alex, **NOVEMBER))["expense_count"] == 1
    assert await by_category(api, alex) == [("Groceries", 100000, 300000, 1)]
    assert await by_category(api, sam) == [("Travel & Transport", 45600, 45600, 1), ("Food & Dining", 12300, 12300, 1)]
    week = await get(api, "trends", alex, granularity="week", **{"from": "2026-11-16", "to": "2026-11-22"})
    assert buckets(week) == [("2026-11-16", "2026-11-22", 100000, 300000, 100000, 300000)]

    # A client-supplied user id is ignored: the user always comes from the token.
    spoofed = await get(api, "summary", alex, user_id=str(sam.id), **NOVEMBER)
    assert (spoofed["share_paise"], spoofed["cash_paid_paise"]) == (100000, 300000)


async def test_an_edit_shows_up_in_the_next_request(pg, api):
    """No server-side cache: the charts change right after an edit."""
    w = await seed_demo(pg["sessions"])
    alex = w["alex"]
    expense = await add_personal(api, alex, 50000, TRAVEL, MONDAY)
    assert (await figures(api, alex))[:2] == (50000, 50000)

    resp = await api.patch(f"/api/v1/expenses/{expense['id']}",
                           json={"version": expense["version"], "amount_paise": 65000, "category_id": str(FOOD)},
                           headers=bearer(alex))
    assert resp.status_code == 200, resp.text
    assert (await figures(api, alex))[:2] == (65000, 65000)
    assert await by_category(api, alex) == [("Food & Dining", 65000, 65000, 1)]


# ==============================================================================
# Group filter
# ==============================================================================


async def test_group_filter_member_past_member_and_stranger(pg, api):
    w = await seed_demo(pg["sessions"])
    alex, casey, sam, group = w["alex"], w["casey"], w["sam"], w["group"]
    await add_shared(api, group, alex, 300000, GROCERIES, MONDAY)
    await add_personal(api, alex, 50000, TRAVEL, MONDAY)
    gid = str(group.id)

    # Member: personal expenses are left out under the group filter.
    assert await figures(api, alex, group_id=gid) == (100000, 300000, 200000, 0)
    assert await figures(api, alex) == (150000, 350000, 200000, 0)
    assert await by_category(api, alex, group_id=gid) == [("Groceries", 100000, 300000, 1)]
    trend = await get(api, "trends", alex, granularity="month", group_id=gid, **NOVEMBER)
    assert (trend["group_id"], trend["total_share_paise"], trend["total_cash_paid_paise"]) == (gid, 100000, 300000)

    # Past member: Casey left the group and still sees their history in it.
    async with pg["sessions"]() as s:
        await s.execute(update(GroupMember)
                        .where(GroupMember.group_id == group.id, GroupMember.user_id == casey.id)
                        .values(status=GroupMemberStatus.LEFT.value))
        await s.commit()
    assert await figures(api, casey, group_id=gid) == (100000, 0, 0, 100000)
    assert await by_category(api, casey, group_id=gid) == [("Groceries", 100000, 0, 1)]

    # Stranger, and a group that does not exist: 404 GROUP_NOT_FOUND on every endpoint.
    for path in ENDPOINTS:
        for group_id in (gid, str(uuid.uuid4())):
            resp = await api.get(f"/api/v1/analytics/{path}", params={"group_id": group_id, **NOVEMBER},
                                 headers=bearer(sam))
            assert resp.status_code == 404, (path, resp.text)
            assert resp.json()["code"] == "GROUP_NOT_FOUND"


# ==============================================================================
# Validation and authentication
# ==============================================================================


async def test_range_validation_and_authentication(pg, api):
    w = await seed_demo(pg["sessions"])
    h = bearer(w["alex"])
    for path in ENDPOINTS:
        bad = await api.get(f"/api/v1/analytics/{path}", params={"from": "2026-11-20", "to": "2026-11-01"}, headers=h)
        assert (bad.status_code, bad.json()["code"]) == (400, "INVALID_RANGE"), path
        # 731 days (two years) is the limit, inclusive of both ends.
        big = await api.get(f"/api/v1/analytics/{path}", params={"from": "2024-11-19", "to": "2026-11-20"}, headers=h)
        assert (big.status_code, big.json()["code"]) == (400, "RANGE_TOO_LARGE"), path
        ok = await api.get(f"/api/v1/analytics/{path}", params={"from": "2024-11-20", "to": "2026-11-20"}, headers=h)
        assert ok.status_code == 200, (path, ok.text)
        for params in ({"from": "2026-13-01"}, {"to": "yesterday"}, {"group_id": "not-a-uuid"}):
            resp = await api.get(f"/api/v1/analytics/{path}", params=params, headers=h)
            assert (resp.status_code, resp.json()["code"]) == (422, "VALIDATION_ERROR"), (path, params)
        for headers in ({}, {"Authorization": "Bearer not-a-token"}):
            resp = await api.get(f"/api/v1/analytics/{path}", params=NOVEMBER, headers=headers)
            assert resp.status_code == 401, (path, headers)
    resp = await api.get("/api/v1/analytics/trends", params={"granularity": "year"}, headers=h)
    assert (resp.status_code, resp.json()["code"]) == (422, "VALIDATION_ERROR")
