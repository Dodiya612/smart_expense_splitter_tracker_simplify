"""Analytics API tests (US-12 / T-42).

The demo dataset (PRODUCT.md section 05, ledger.md section 8) step by step:
  1. Alex pays ₹3,000 groceries split by three  → Alex share ₹1,000.00, cash ₹3,000.00
  2. Blair repays Alex ₹1,000 (settlement)        → unchanged
  3. Alex adds a personal ₹500 metro recharge     → share ₹1,500.00, cash ₹3,500.00
  4. Casey pays ₹100 chai split by three          → share ₹1,533.34, cash ₹3,500.00

There is no PostgreSQL in this test run, so the three aggregate statements are
answered by ``FakeAnalyticsSession`` with a small reference implementation of the
documented rules (share vs cash paid, deleted excluded, settlements never read,
Monday weeks). Everything else is the real code: routes, validation, authorization,
bucket filling, cumulative totals, sorting, and the ledger engine for balances.
The SQL itself is checked structurally here and end to end in
tests/test_analytics_pg.py (skipped when no local PostgreSQL is reachable).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import Expense
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus, GroupType
from app.models.user import User
from app.services import analytics_service, settlement_service
from app.services.analytics_service import (
    ANALYTICS_OPTION,
    AnalyticsFilter,
    categories_statement,
    summary_statement,
    trends_statement,
)
from app.services.ledger import allocate
from tests.test_settlements import FakeSettlementAsyncSession, FakeSettlementDB

GROCERIES = uuid.UUID("00000000-0000-4000-8000-000000000002")
TRAVEL = uuid.UUID("00000000-0000-4000-8000-000000000003")
FOOD = uuid.UUID("00000000-0000-4000-8000-000000000001")
DAY1 = date(2026, 11, 16)  # a Monday


# ==============================================================================
# Fake session answering the analytics statements
# ==============================================================================


class _Result:
    def __init__(self, rows: list[SimpleNamespace]):
        self._rows = rows

    def one(self) -> SimpleNamespace:
        return self._rows[0]

    def all(self) -> list[SimpleNamespace]:
        return list(self._rows)


class _Scalars:
    def __init__(self, items: list[Any]):
        self._items = items

    def scalars(self) -> "_Scalars":
        return self

    def all(self) -> list[Any]:
        return list(self._items)


def _reference_rows(db: FakeSettlementDB, f: AnalyticsFilter) -> list[tuple[uuid.UUID, date, uuid.UUID, int, int]]:
    """(expense_id, date, category_id, share, cash) per the documented rules."""
    out = []
    for e in db.expenses.values():
        if e.deleted_at is not None or not (f.start <= e.expense_date <= f.end):
            continue
        if f.group_id is not None and e.group_id != f.group_id:
            continue
        if e.group_id is None:
            if e.user_id == f.user_id:
                out.append((e.id, e.expense_date, e.category_id, e.amount_minor, e.amount_minor))
            continue
        for s in db.expense_shares.values():
            if s.expense_id == e.id and s.user_id == f.user_id:
                out.append((e.id, e.expense_date, e.category_id, s.amount_paise, 0))
        for p in db.expense_payments.values():
            if p.expense_id == e.id and p.user_id == f.user_id:
                out.append((e.id, e.expense_date, e.category_id, 0, p.amount_paise))
    return out


def _trunc(d: date, unit: str) -> date:
    if unit == "week":
        return d - timedelta(days=d.weekday())
    if unit == "month":
        return d.replace(day=1)
    return d


class FakeAnalyticsSession(FakeSettlementAsyncSession):
    def __init__(self, db: FakeSettlementDB):
        super().__init__(db)
        self.analytics_sql: list[str] = []

    async def execute(self, stmt: Any) -> Any:
        opts = stmt.get_execution_options().get(ANALYTICS_OPTION) if hasattr(stmt, "get_execution_options") else None
        if opts:
            self.analytics_sql.append(str(stmt.compile(dialect=postgresql.dialect())))
            rows = _reference_rows(self.db, opts["filter"])
            if opts["kind"] == "summary":
                return _Result([SimpleNamespace(
                    share_paise=sum(r[3] for r in rows),
                    cash_paid_paise=sum(r[4] for r in rows),
                    expense_count=len({r[0] for r in rows}),
                )])
            if opts["kind"] == "trends":
                buckets: dict[date, list[int]] = {}
                for r in rows:
                    b = buckets.setdefault(_trunc(r[1], opts["granularity"]), [0, 0])
                    b[0] += r[3]
                    b[1] += r[4]
                return _Result([
                    SimpleNamespace(bucket_start=k, share_paise=v[0], cash_paid_paise=v[1])
                    for k, v in sorted(buckets.items())
                ])
            cats: dict[uuid.UUID, dict[str, Any]] = {}
            for r in rows:
                c = cats.setdefault(r[2], {"share": 0, "cash": 0, "ids": set()})
                c["share"] += r[3]
                c["cash"] += r[4]
                c["ids"].add(r[0])
            items = [
                SimpleNamespace(
                    category_id=cid, category_name=self.db.categories[cid].name,
                    share_paise=v["share"], cash_paid_paise=v["cash"], expense_count=len(v["ids"]),
                )
                for cid, v in cats.items()
            ]
            items.sort(key=lambda i: (-i.share_paise, -i.cash_paid_paise, i.category_name))
            return _Result(items)

        sql = str(stmt).lower()
        if sql.startswith("select group_members.group_id"):
            uid = next(v for k, v in stmt.compile().params.items() if "user_id" in k)
            return _Scalars([
                m.group_id for m in self.db.group_members.values()
                if m.user_id == uid and self.db.groups[m.group_id].archived_at is None
            ])
        return await super().execute(stmt)


# ==============================================================================
# World: Alex, Blair, Casey in "Flat Expenses", plus a stranger
# ==============================================================================


class World:
    def __init__(self) -> None:
        self.db = FakeSettlementDB()
        self.session = FakeAnalyticsSession(self.db)
        self.alex, self.blair, self.casey, self.stranger = (
            User(id=uuid.UUID(f"{i}" * 8 + "-1111-4111-8111-" + f"{i}" * 12), email=f"{n}@example.com",
                 name=n.title(), hashed_password="x", is_active=True)
            for i, n in ((1, "alex"), (2, "blair"), (3, "casey"), (9, "stranger"))
        )
        for u in (self.alex, self.blair, self.casey, self.stranger):
            self.db.users[u.id] = u
        for cid, name in ((FOOD, "Food & Dining"), (GROCERIES, "Groceries"), (TRAVEL, "Travel & Transport")):
            self.db.categories[cid] = Category(id=cid, name=name, is_default=True)
        now = datetime.now(UTC)
        self.group = Group(id=uuid.uuid4(), name="Flat Expenses", type=GroupType.FLAT.value,
                           created_by=self.alex.id, created_at=now, updated_at=now)
        self.db.groups[self.group.id] = self.group
        members = []
        for i, u in enumerate((self.alex, self.blair, self.casey)):
            m = GroupMember(group_id=self.group.id, user_id=u.id,
                            role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
                            status=GroupMemberStatus.ACTIVE.value, joined_at=now + timedelta(seconds=i), updated_at=now)
            m.user = u
            self.db.group_members[(self.group.id, u.id)] = m
            members.append(m)
        self.group.members = members
        self.group.creator = self.alex

    def headers(self, user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id, email=user.email)}"}

    def add_personal(self, user: User, amount: int, category: uuid.UUID, day: date, deleted: bool = False) -> Expense:
        now = datetime.now(UTC)
        e = Expense(id=uuid.uuid4(), user_id=user.id, group_id=None, category_id=category, amount_minor=amount,
                    description="Personal", expense_date=day, version=1, created_at=now, updated_at=now,
                    deleted_at=now if deleted else None)
        self.db.expenses[e.id] = e
        return e


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
async def client(world: World):
    async def override_get_db():
        yield world.session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def add_shared(client: AsyncClient, w: World, payer: User, amount: int, category: uuid.UUID, day: date) -> dict:
    resp = await client.post(
        f"/api/v1/groups/{w.group.id}/expenses",
        json={"amount_paise": amount, "description": "Shared", "category_id": str(category),
              "split_mode": "equal", "expense_date": day.isoformat()},
        headers=w.headers(payer),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def summary(client: AsyncClient, w: World, user: User, **params: str) -> dict:
    query = {"from": "2026-11-01", "to": "2026-11-30", **params}
    resp = await client.get("/api/v1/analytics/summary", params=query, headers=w.headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ==============================================================================
# Demo dataset, step by step
# ==============================================================================


@pytest.mark.asyncio
async def test_demo_dataset_step_by_step(client, world):
    w = world

    # Step 1: Alex pays ₹3,000 for groceries, split equally by three.
    await add_shared(client, w, w.alex, 300000, GROCERIES, DAY1)
    shares_1 = allocate(300000, [str(w.alex.id), str(w.blair.id), str(w.casey.id)], "equal")
    a, b, c = [await summary(client, w, u) for u in (w.alex, w.blair, w.casey)]
    assert (a["share_paise"], a["cash_paid_paise"]) == (100000, 300000)
    assert (b["share_paise"], b["cash_paid_paise"]) == (100000, 0)
    assert (c["share_paise"], c["cash_paid_paise"]) == (100000, 0)
    assert a["share_paise"] == shares_1[str(w.alex.id)]
    assert (a["owed_to_you_paise"], a["you_owe_paise"]) == (200000, 0)
    assert (b["owed_to_you_paise"], b["you_owe_paise"]) == (0, 100000)

    # Step 2: Blair repays Alex ₹1,000. A settlement is never spending or income.
    resp = await client.post(
        f"/api/v1/groups/{w.group.id}/settlements",
        json={"payer_id": str(w.blair.id), "payee_id": str(w.alex.id), "amount_paise": 100000},
        headers=w.headers(w.blair),
    )
    assert resp.status_code == 201, resp.text
    a, b = [await summary(client, w, u) for u in (w.alex, w.blair)]
    assert (a["share_paise"], a["cash_paid_paise"]) == (100000, 300000)
    assert (b["share_paise"], b["cash_paid_paise"]) == (100000, 0)
    assert (a["owed_to_you_paise"], b["you_owe_paise"]) == (100000, 0)

    # Step 3: Alex adds a personal ₹500 metro recharge.
    w.add_personal(w.alex, 50000, TRAVEL, DAY1 + timedelta(days=1))
    a, b = [await summary(client, w, u) for u in (w.alex, w.blair)]
    assert (a["share_paise"], a["cash_paid_paise"]) == (150000, 350000)
    assert (b["share_paise"], b["cash_paid_paise"]) == (100000, 0)
    assert a["owed_to_you_paise"] == 100000  # personal expenses never touch group balances

    # Step 4: Casey pays ₹100 for chai, split by three; the extra paisa goes to Alex.
    await add_shared(client, w, w.casey, 10000, FOOD, DAY1 + timedelta(days=2))
    shares_4 = allocate(10000, [str(w.alex.id), str(w.blair.id), str(w.casey.id)], "equal")
    assert shares_4[str(w.alex.id)] == 3334
    a, b, c = [await summary(client, w, u) for u in (w.alex, w.blair, w.casey)]
    assert (a["share_paise"], a["cash_paid_paise"]) == (153334, 350000)
    assert (b["share_paise"], b["cash_paid_paise"]) == (103333, 0)
    assert (c["share_paise"], c["cash_paid_paise"]) == (103333, 10000)
    assert a["share_paise"] == 100000 + 50000 + shares_4[str(w.alex.id)]
    assert a["expense_count"] == 3
    assert b["expense_count"] == 2
    # Ledger engine: Alex +966.66, Blair −33.33, Casey −933.33 (PRODUCT.md section 05).
    assert (a["owed_to_you_paise"], a["you_owe_paise"]) == (96666, 0)
    assert (b["owed_to_you_paise"], b["you_owe_paise"]) == (0, 3333)
    assert (c["owed_to_you_paise"], c["you_owe_paise"]) == (0, 93333)
    assert a["timezone"] == "Asia/Kolkata"

    # Categories (as stored): Groceries, Travel & Transport, Food & Dining.
    resp = await client.get("/api/v1/analytics/categories", params={"from": "2026-11-01", "to": "2026-11-30"},
                            headers=w.headers(w.alex))
    assert resp.status_code == 200
    cats = resp.json()
    assert [(i["category_name"], i["share_paise"], i["cash_paid_paise"], i["expense_count"]) for i in cats["categories"]] == [
        ("Groceries", 100000, 300000, 1),
        ("Travel & Transport", 50000, 50000, 1),
        ("Food & Dining", 3334, 0, 1),
    ]
    assert (cats["total_share_paise"], cats["total_cash_paid_paise"]) == (153334, 350000)

    resp = await client.get("/api/v1/analytics/categories", params={"from": "2026-11-01", "to": "2026-11-30"},
                            headers=w.headers(w.casey))
    assert [(i["category_name"], i["share_paise"], i["cash_paid_paise"]) for i in resp.json()["categories"]] == [
        ("Groceries", 100000, 0),
        ("Food & Dining", 3333, 10000),
    ]


# ==============================================================================
# Trends: buckets, cumulative, Asia/Kolkata, Monday weeks
# ==============================================================================


@pytest.mark.asyncio
async def test_daily_trend_has_every_day_and_running_totals(client, world):
    w = world
    await add_shared(client, w, w.alex, 300000, GROCERIES, DAY1)
    w.add_personal(w.alex, 50000, TRAVEL, DAY1 + timedelta(days=2))
    resp = await client.get(
        "/api/v1/analytics/trends",
        params={"granularity": "day", "from": "2026-11-15", "to": "2026-11-19"},
        headers=w.headers(w.alex),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [(b["bucket_start"], b["share_paise"], b["cash_paid_paise"], b["cumulative_share_paise"],
             b["cumulative_cash_paid_paise"]) for b in body["buckets"]] == [
        ("2026-11-15", 0, 0, 0, 0),
        ("2026-11-16", 100000, 300000, 100000, 300000),
        ("2026-11-17", 0, 0, 100000, 300000),
        ("2026-11-18", 50000, 50000, 150000, 350000),
        ("2026-11-19", 0, 0, 150000, 350000),
    ]
    assert (body["total_share_paise"], body["total_cash_paid_paise"]) == (150000, 350000)
    assert body["granularity"] == "day"


@pytest.mark.asyncio
async def test_weeks_start_on_monday_and_months_on_the_first(client, world):
    w = world
    w.add_personal(w.alex, 1000, FOOD, date(2026, 11, 15))  # Sunday
    w.add_personal(w.alex, 2000, FOOD, date(2026, 11, 16))  # Monday
    w.add_personal(w.alex, 4000, FOOD, date(2026, 12, 1))
    resp = await client.get("/api/v1/analytics/trends",
                            params={"granularity": "week", "from": "2026-11-10", "to": "2026-11-24"},
                            headers=w.headers(w.alex))
    weeks = resp.json()["buckets"]
    assert [(b["bucket_start"], b["bucket_end"], b["share_paise"]) for b in weeks] == [
        ("2026-11-09", "2026-11-15", 1000),
        ("2026-11-16", "2026-11-22", 2000),
        ("2026-11-23", "2026-11-29", 0),
    ]
    assert all(date.fromisoformat(b["bucket_start"]).weekday() == 0 for b in weeks)

    resp = await client.get("/api/v1/analytics/trends",
                            params={"granularity": "month", "from": "2026-10-05", "to": "2026-12-31"},
                            headers=w.headers(w.alex))
    months = resp.json()["buckets"]
    assert [(b["bucket_start"], b["bucket_end"], b["share_paise"], b["cumulative_share_paise"]) for b in months] == [
        ("2026-10-01", "2026-10-31", 0, 0),
        ("2026-11-01", "2026-11-30", 3000, 3000),
        ("2026-12-01", "2026-12-31", 4000, 7000),
    ]


@pytest.mark.asyncio
async def test_kolkata_dates_late_evening_and_after_midnight(client, world, monkeypatch):
    """23:30 IST on 19 Nov and 00:30 IST on 20 Nov are different days, although both
    are 19 Nov in UTC. Expenses carry the Asia/Kolkata calendar date, and the default
    range ("today") is computed in Asia/Kolkata, not UTC."""
    w = world
    late_evening_utc = datetime(2026, 11, 19, 18, 0, tzinfo=UTC)   # 23:30 IST, 19 Nov
    after_midnight_utc = datetime(2026, 11, 19, 19, 0, tzinfo=UTC)  # 00:30 IST, 20 Nov
    assert late_evening_utc.astimezone(settlement_service.IST).date() == date(2026, 11, 19)
    assert after_midnight_utc.astimezone(settlement_service.IST).date() == date(2026, 11, 20)
    assert after_midnight_utc.date() == date(2026, 11, 19)  # UTC would put it on the wrong day

    w.add_personal(w.alex, 1100, FOOD, late_evening_utc.astimezone(settlement_service.IST).date())
    w.add_personal(w.alex, 2200, FOOD, after_midnight_utc.astimezone(settlement_service.IST).date())

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return after_midnight_utc.astimezone(tz) if tz else after_midnight_utc.replace(tzinfo=None)

    monkeypatch.setattr(settlement_service, "datetime", FrozenDateTime)
    assert settlement_service.today_in_kolkata() == date(2026, 11, 20)

    resp = await client.get("/api/v1/analytics/trends", params={"granularity": "day"}, headers=w.headers(w.alex))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["from_date"], body["to_date"]) == ("2026-11-01", "2026-11-20")
    by_day = {b["bucket_start"]: b["share_paise"] for b in body["buckets"]}
    assert by_day["2026-11-19"] == 1100
    assert by_day["2026-11-20"] == 2200
    assert len(body["buckets"]) == 20


# ==============================================================================
# What never counts, and whose data
# ==============================================================================


@pytest.mark.asyncio
async def test_deleted_expenses_and_settlements_are_excluded(client, world):
    w = world
    await add_shared(client, w, w.alex, 300000, GROCERIES, DAY1)
    w.add_personal(w.alex, 99900, TRAVEL, DAY1, deleted=True)
    before = await summary(client, w, w.alex)
    resp = await client.post(
        f"/api/v1/groups/{w.group.id}/settlements",
        json={"payer_id": str(w.casey.id), "payee_id": str(w.alex.id), "amount_paise": 100000},
        headers=w.headers(w.casey),
    )
    assert resp.status_code == 201
    after = await summary(client, w, w.alex)
    assert (before["share_paise"], before["cash_paid_paise"]) == (100000, 300000)
    assert (after["share_paise"], after["cash_paid_paise"]) == (100000, 300000)
    casey = await summary(client, w, w.casey)
    assert (casey["share_paise"], casey["cash_paid_paise"]) == (100000, 0)  # repayment is not cash paid
    # A shared expense deleted later disappears from everyone's totals.
    for e in w.db.expenses.values():
        e.deleted_at = datetime.now(UTC)
    gone = await summary(client, w, w.alex)
    assert (gone["share_paise"], gone["cash_paid_paise"], gone["expense_count"]) == (0, 0, 0)


@pytest.mark.asyncio
async def test_another_users_data_is_never_included(client, world):
    w = world
    w.add_personal(w.stranger, 777700, FOOD, DAY1)
    await add_shared(client, w, w.alex, 300000, GROCERIES, DAY1)
    stranger = await summary(client, w, w.stranger)
    assert (stranger["share_paise"], stranger["cash_paid_paise"], stranger["expense_count"]) == (777700, 777700, 1)
    assert (stranger["owed_to_you_paise"], stranger["you_owe_paise"]) == (0, 0)
    alex = await summary(client, w, w.alex)
    assert alex["share_paise"] == 100000
    # A client-supplied user id is ignored: the signed-in user is always used.
    resp = await client.get("/api/v1/analytics/summary",
                            params={"from": "2026-11-01", "to": "2026-11-30", "user_id": str(w.stranger.id)},
                            headers=w.headers(w.alex))
    assert resp.json()["share_paise"] == 100000


# ==============================================================================
# Group filter
# ==============================================================================


@pytest.mark.asyncio
async def test_group_filter_members_past_members_and_strangers(client, world):
    w = world
    await add_shared(client, w, w.alex, 300000, GROCERIES, DAY1)
    w.add_personal(w.alex, 50000, TRAVEL, DAY1)
    gid = str(w.group.id)

    alex = await summary(client, w, w.alex, group_id=gid)
    assert (alex["share_paise"], alex["cash_paid_paise"], alex["group_id"]) == (100000, 300000, gid)
    assert alex["owed_to_you_paise"] == 200000

    # A member who left still sees their history in that group.
    w.db.group_members[(w.group.id, w.casey.id)].status = GroupMemberStatus.LEFT.value
    casey = await summary(client, w, w.casey, group_id=gid)
    assert (casey["share_paise"], casey["you_owe_paise"]) == (100000, 100000)

    for path in ("summary", "trends", "categories"):
        for group in (gid, str(uuid.uuid4())):
            resp = await client.get(f"/api/v1/analytics/{path}", params={"group_id": group},
                                    headers=w.headers(w.stranger))
            assert resp.status_code == 404, (path, resp.text)
            assert resp.json()["code"] == "GROUP_NOT_FOUND"


# ==============================================================================
# Validation and authentication
# ==============================================================================


@pytest.mark.asyncio
async def test_range_validation(client, world):
    w = world
    h = w.headers(w.alex)
    bad = await client.get("/api/v1/analytics/summary", params={"from": "2026-11-20", "to": "2026-11-01"}, headers=h)
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_RANGE"
    big = await client.get("/api/v1/analytics/trends", params={"from": "2024-01-01", "to": "2026-01-01"}, headers=h)
    assert big.status_code == 400
    assert big.json()["code"] == "RANGE_TOO_LARGE"
    ok = await client.get("/api/v1/analytics/trends", params={"from": "2025-01-01", "to": "2026-12-31", "granularity": "month"}, headers=h)
    assert ok.status_code == 200
    assert len(ok.json()["buckets"]) == 24
    for params in ({"from": "2026-13-01"}, {"to": "yesterday"}, {"granularity": "year"}, {"group_id": "not-a-uuid"}):
        resp = await client.get("/api/v1/analytics/trends", params=params, headers=h)
        assert resp.status_code == 422, params
        assert resp.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_unauthenticated_requests_get_401(client):
    for path in ("summary", "trends", "categories"):
        resp = await client.get(f"/api/v1/analytics/{path}")
        assert resp.status_code == 401, path


@pytest.mark.asyncio
async def test_no_expenses_gives_zeros_and_empty_buckets(client, world):
    w = world
    s = await summary(client, w, w.blair)
    assert (s["share_paise"], s["cash_paid_paise"], s["expense_count"], s["owed_to_you_paise"], s["you_owe_paise"]) == (0, 0, 0, 0, 0)
    resp = await client.get("/api/v1/analytics/trends", params={"from": "2026-11-01", "to": "2026-11-07"},
                            headers=w.headers(w.blair))
    assert [b["share_paise"] for b in resp.json()["buckets"]] == [0] * 7
    resp = await client.get("/api/v1/analytics/categories", headers=w.headers(w.blair))
    assert resp.json()["categories"] == []


# ==============================================================================
# Pure helpers and SQL shape
# ==============================================================================


def test_resolve_range_defaults_to_this_month_in_kolkata():
    today = date(2026, 11, 20)
    assert analytics_service.resolve_range(None, None, today) == (date(2026, 11, 1), today)
    assert analytics_service.resolve_range(None, date(2026, 2, 14), today) == (date(2026, 2, 1), date(2026, 2, 14))
    assert analytics_service.resolve_range(date(2024, 11, 21), date(2026, 11, 20), today)[0] == date(2024, 11, 21)


def test_sql_counts_shares_and_payments_and_never_settlements():
    f = AnalyticsFilter(uuid.uuid4(), date(2026, 11, 1), date(2026, 11, 30))
    for stmt in (summary_statement(f), trends_statement(f, "week"), categories_statement(f)):
        sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
        assert "settlements" not in sql
        assert sql.count("expenses.deleted_at is null") == 3
        assert "expenses.group_id is null" in sql  # personal leg
        assert "expense_shares.user_id =" in sql
        assert "expense_payments.user_id =" in sql
    week_sql = str(trends_statement(f, "week").compile(dialect=postgresql.dialect())).lower()
    assert "date_trunc('week'" in week_sql

    grouped = AnalyticsFilter(f.user_id, f.start, f.end, group_id=uuid.uuid4())
    sql = str(summary_statement(grouped).compile(dialect=postgresql.dialect())).lower()
    assert "expenses.group_id is null" not in sql  # personal expenses excluded with a group filter
    assert sql.count("expenses.group_id =") == 2
