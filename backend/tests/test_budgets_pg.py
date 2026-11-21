"""Real-PostgreSQL checks for budgets (US-25 / T-48).

T-48 Done-when: "threshold tests pass for 79%, 80%, 100% and edits that go back under."

The module builds ONE throwaway database with ``alembic upgrade head`` (so the real 016
migration, its UNIQUE keys, partial indexes and CHECKs are what is tested), runs every test
against it with its own users, and drops it at the end. The expense, shared-expense,
settlement and recurring services, the post-commit budget checks and the notification
centre all run for real; only the clock is fake (March 2025, Asia/Kolkata).

SKIPPED when no local PostgreSQL is reachable. Same rules as the other *_pg.py files:
COINSCIOUS_TEST_PG_URL is an admin URL on a LOCAL server (default
postgresql+asyncpg://postgres:postgres@localhost:5432/postgres); any other host is refused.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.budget import Budget, BudgetAlert
from app.models.expense import Expense
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus, GroupType
from app.models.notification import Notification
from app.models.user import User
from app.schemas.expense import ExpenseCreate
from app.schemas.recurring import RecurringRuleCreate
from app.services import budget_service, notifications, recurring_service
from app.services import expenses as expense_service
from app.services.budget_service import _check_users as real_check_users
from app.services.notifications import _persist as real_persist
from app.services.notifications import active_member_roles as real_active_member_roles

DEFAULT_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
ADMIN_URL = os.getenv("COINSCIOUS_TEST_PG_URL", DEFAULT_ADMIN_URL)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
BACKEND_DIR = Path(__file__).resolve().parent.parent
D = date.fromisoformat
FOOD = uuid.UUID("00000000-0000-4000-8000-000000000001")  # default categories from migration 004
GROCERIES = uuid.UUID("00000000-0000-4000-8000-000000000002")
WARNING, EXCEEDED = "budget_warning", "budget_exceeded"


def ist(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp + "+05:30").astimezone(UTC)


def _admin_engine(url: URL):
    return create_engine(
        url.set(drivername="postgresql+psycopg"),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )


@pytest.fixture(scope="module")
def migrated_db() -> Iterator[URL]:
    """A throwaway database built from the Alembic migrations; dropped afterwards."""
    admin_url = make_url(ADMIN_URL)
    if admin_url.host not in LOCAL_HOSTS:
        pytest.skip(f"COINSCIOUS_TEST_PG_URL must point at a local server, got host '{admin_url.host}'.")
    admin = _admin_engine(admin_url)
    name = f"coinscious_t48_{uuid.uuid4().hex[:12]}"
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - any connection problem means "no Postgres here"
        admin.dispose()
        pytest.skip(
            "No local PostgreSQL reachable at "
            f"{admin_url.render_as_string(hide_password=True)} ({type(exc).__name__}); "
            "T-48 Done-when not verified on a real database. Set COINSCIOUS_TEST_PG_URL to run."
        )
    target = admin_url.set(database=name)
    try:
        secret_url = target.render_as_string(hide_password=False)
        env = {
            **os.environ,
            "DATABASE_URL": secret_url,
            "DEBUG": "false",
            "PYTHONPATH": os.pathsep.join([str(BACKEND_DIR.parent), str(BACKEND_DIR)]),
        }
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=300,
        )
        output = (proc.stdout + proc.stderr).replace(secret_url, "<database url>")
        assert proc.returncode == 0, f"alembic upgrade head failed:\n{output[-3000:]}"
        assert "016_budgets" in output
        yield target
    finally:
        with admin.connect() as conn:
            conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :d AND pid <> pg_backend_pid()"),
                {"d": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture
async def pg(migrated_db, monkeypatch) -> AsyncIterator[dict[str, Any]]:
    """Real sessions for the services, the budget checks and the notification centre."""
    engine = create_async_engine(migrated_db, pool_size=10, max_overflow=20)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    clock = {"now": ist("2025-03-12T10:00:00")}  # Wednesday; week 10-16 March, month March
    monkeypatch.setattr(budget_service, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(budget_service, "_check_users", real_check_users)
    monkeypatch.setattr(budget_service, "_now", lambda: clock["now"])
    monkeypatch.setattr(notifications, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(notifications, "_persist", real_persist)
    monkeypatch.setattr(notifications, "active_member_roles", real_active_member_roles)
    monkeypatch.setattr(recurring_service, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(recurring_service, "_now", lambda: clock["now"])

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as api:
            yield {"engine": engine, "sessions": sessions, "clock": clock, "api": api}
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ==============================================================================
# Seed data and helpers
# ==============================================================================


async def seed(sessions: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Alex (group admin), Blair and Casey in one group; Sam is a stranger."""
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    users = [
        User(id=uuid.uuid4(), email=f"{n}-{tag}@example.com", name=n.title(), hashed_password="x", is_active=True)
        for n in ("alex", "blair", "casey", "sam")
    ]
    group = Group(id=uuid.uuid4(), name=f"Flat {tag}", type=GroupType.FLAT.value,
                  created_by=users[0].id, created_at=now, updated_at=now)
    async with sessions() as s:
        s.add_all([*users, group])
        await s.flush()
        for i, u in enumerate(users[:3]):
            s.add(GroupMember(
                group_id=group.id, user_id=u.id,
                role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
                status=GroupMemberStatus.ACTIVE.value, joined_at=now + timedelta(seconds=i), updated_at=now,
            ))
        await s.commit()
    return {"alex": users[0], "blair": users[1], "casey": users[2], "sam": users[3], "group": group}


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, email=user.email)}"}


async def create_budget(api: AsyncClient, user: User, period: str, limit: int, category: uuid.UUID | None = None) -> str:
    body: dict[str, Any] = {"period": period, "limitPaise": limit}
    if category is not None:
        body["categoryId"] = str(category)
    resp = await api.post("/api/v1/budgets", json=body, headers=bearer(user))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["id"]


async def progress(api: AsyncClient, user: User, budget_id: str) -> dict[str, Any]:
    resp = await api.get(f"/api/v1/budgets/{budget_id}", headers=bearer(user))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["progress"]


async def add_personal(api: AsyncClient, user: User, amount: int, day: str, category: uuid.UUID = FOOD) -> dict[str, Any]:
    resp = await api.post(
        "/api/v1/expenses",
        json={"amount_paise": amount, "description": "Personal", "category_id": str(category), "expense_date": day},
        headers=bearer(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def edit_personal(api: AsyncClient, user: User, exp: dict[str, Any], amount: int) -> dict[str, Any]:
    resp = await api.patch(
        f"/api/v1/expenses/{exp['id']}", json={"amount_paise": amount, "version": exp["version"]}, headers=bearer(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def add_shared(api: AsyncClient, group: Group, actor: User, amount: int, day: str,
                     participants: list[User], payer: User | None = None) -> dict[str, Any]:
    resp = await api.post(
        f"/api/v1/groups/{group.id}/expenses",
        json={"amount_paise": amount, "description": "Shared", "category_id": str(FOOD), "split_mode": "equal",
              "expense_date": day, "paid_by_user_id": str((payer or actor).id),
              "participant_user_ids": [str(u.id) for u in participants]},
        headers=bearer(actor),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def edit_shared(api: AsyncClient, group: Group, actor: User, exp: dict[str, Any], amount: int,
                      participants: list[User]) -> dict[str, Any]:
    resp = await api.patch(
        f"/api/v1/groups/{group.id}/expenses/{exp['id']}",
        json={"version": exp["version"], "amount_paise": amount, "split_mode": "equal",
              "participant_user_ids": [str(u.id) for u in participants]},
        headers=bearer(actor),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def alert_rows(sessions, budget_id: str) -> list[tuple[str, int, bool]]:
    async with sessions() as s:
        rows = await s.execute(
            select(BudgetAlert.period_start, BudgetAlert.threshold, BudgetAlert.suppressed)
            .where(BudgetAlert.budget_id == uuid.UUID(budget_id))
            .order_by(BudgetAlert.period_start, BudgetAlert.threshold)
        )
        return [(p.isoformat(), t, sup) for p, t, sup in rows.all()]


async def notices(sessions, user: User) -> list[tuple[str, str]]:
    async with sessions() as s:
        rows = await s.execute(
            select(Notification.kind, Notification.dedupe_key)
            .where(Notification.user_id == user.id, Notification.kind.in_((WARNING, EXCEEDED)))
            .order_by(Notification.created_at, Notification.dedupe_key)
        )
        return [(k, key) for k, key in rows.all()]


def key(budget_id: str, period_start: str, threshold: int) -> str:
    return f"budget_threshold:{budget_id}:{period_start}:{threshold}"


def scenario(name: str, spent: int, limit: int, expected: list[str], sent: list[str]) -> None:
    """One row of the Done-when table (shown with pytest -s)."""
    ok = "OK" if expected == sent else "MISMATCH"
    print(f"DONE-WHEN | {name} | {spent} | {limit} | {spent * 100 // limit}% | {expected} | {sent} | {ok}")
    assert expected == sent, name


def kinds(sent: list[tuple[str, str]]) -> list[str]:
    return ["80%" if k == WARNING else "100%" for k, _ in sent]


# ==============================================================================
# T-48 DONE-WHEN: 79%, 80%, 100% and edits that go back under
# ==============================================================================


async def test_done_when_79_80_and_100_percent_each_alert_once(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    budget = await create_budget(api, alex, "monthly", 10_000)

    await add_personal(api, alex, 7_900, "2025-03-03")
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["percentUsed"], p["status"]) == (7_900, 79, "under")
    assert await alert_rows(sessions, budget) == []
    scenario("79%: no alert", 7_900, 10_000, [], kinds(await notices(sessions, alex)))

    await add_personal(api, alex, 100, "2025-03-04")
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["percentUsed"], p["status"]) == (8_000, 80, "warning")
    assert await alert_rows(sessions, budget) == [("2025-03-01", 80, False)]
    assert await notices(sessions, alex) == [(WARNING, key(budget, "2025-03-01", 80))]
    scenario("exactly 80%: one 80% alert", 8_000, 10_000, ["80%"], kinds(await notices(sessions, alex)))

    await add_personal(api, alex, 1_999, "2025-03-05")
    p = await progress(api, alex, budget)
    assert (p["percentUsed"], p["status"], p["remainingPaise"]) == (99, "warning", 1)
    scenario("99%: still only the 80% alert", 9_999, 10_000, ["80%"], kinds(await notices(sessions, alex)))

    await add_personal(api, alex, 1, "2025-03-31")
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["percentUsed"], p["status"], p["remainingPaise"], p["overByPaise"]) == (
        10_000, 100, "exceeded", 0, 0
    )
    assert await alert_rows(sessions, budget) == [("2025-03-01", 80, False), ("2025-03-01", 100, False)]
    assert await notices(sessions, alex) == [
        (WARNING, key(budget, "2025-03-01", 80)), (EXCEEDED, key(budget, "2025-03-01", 100)),
    ]
    scenario("exactly 100%: one 100% alert", 10_000, 10_000, ["80%", "100%"], kinds(await notices(sessions, alex)))

    await add_personal(api, alex, 5_000, "2025-03-20")
    p = await progress(api, alex, budget)
    assert (p["percentUsed"], p["status"], p["remainingPaise"], p["overByPaise"]) == (150, "exceeded", -5_000, 5_000)
    assert len(await alert_rows(sessions, budget)) == 2
    scenario("150%: nothing new", 15_000, 10_000, ["80%", "100%"], kinds(await notices(sessions, alex)))


async def test_done_when_straight_past_100_sends_only_the_100_alert(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    blair = w["blair"]
    budget = await create_budget(api, blair, "monthly", 10_000)

    exp = await add_personal(api, blair, 15_000, "2025-03-10")
    p = await progress(api, blair, budget)
    assert (p["percentUsed"], p["status"]) == (150, "exceeded")
    # The 80% row exists (so it cannot fire later this month) but was never announced.
    assert await alert_rows(sessions, budget) == [("2025-03-01", 80, True), ("2025-03-01", 100, False)]
    assert await notices(sessions, blair) == [(EXCEEDED, key(budget, "2025-03-01", 100))]
    scenario("0% -> 150%: only the 100% alert", 15_000, 10_000, ["100%"], kinds(await notices(sessions, blair)))

    # Editing back down to 85% shows "warning" at once and still sends no 80% alert.
    await edit_personal(api, blair, exp, 8_500)
    p = await progress(api, blair, budget)
    assert (p["percentUsed"], p["status"]) == (85, "warning")
    scenario("150% -> 85% (edit): no 80% alert", 8_500, 10_000, ["100%"], kinds(await notices(sessions, blair)))


async def test_done_when_edit_back_under_then_over_again_and_next_period(pg):
    api, sessions, clock = pg["api"], pg["sessions"], pg["clock"]
    w = await seed(sessions)
    alex = w["alex"]
    budget = await create_budget(api, alex, "weekly", 10_000)

    exp = await add_personal(api, alex, 8_500, "2025-03-11")
    assert (await progress(api, alex, budget))["status"] == "warning"
    assert await notices(sessions, alex) == [(WARNING, key(budget, "2025-03-10", 80))]

    # Edit back under 80%: progress and status show it at once, nothing new is sent.
    exp = await edit_personal(api, alex, exp, 7_000)
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["percentUsed"], p["status"]) == (7_000, 70, "under")
    scenario("85% -> 70% (edit back under)", 7_000, 10_000, ["80%"], kinds(await notices(sessions, alex)))

    # Over 80% again in the SAME week: still exactly one 80% alert.
    exp = await edit_personal(api, alex, exp, 9_000)
    p = await progress(api, alex, budget)
    assert (p["percentUsed"], p["status"]) == (90, "warning")
    assert await alert_rows(sessions, budget) == [("2025-03-10", 80, False)]
    scenario("70% -> 90% same week: no second 80% alert", 9_000, 10_000, ["80%"],
             kinds(await notices(sessions, alex)))

    # Sunday 23:59 IST is still this week; Monday 00:00 IST starts a fresh week.
    clock["now"] = ist("2025-03-16T23:59:59")
    assert (await progress(api, alex, budget))["periodStart"] == "2025-03-10"
    clock["now"] = ist("2025-03-17T00:00:00")
    p = await progress(api, alex, budget)
    assert (p["periodStart"], p["periodEnd"], p["spentPaise"], p["status"]) == ("2025-03-17", "2025-03-23", 0, "under")

    await add_personal(api, alex, 8_000, "2025-03-17")
    assert await alert_rows(sessions, budget) == [("2025-03-10", 80, False), ("2025-03-17", 80, False)]
    assert await notices(sessions, alex) == [
        (WARNING, key(budget, "2025-03-10", 80)), (WARNING, key(budget, "2025-03-17", 80)),
    ]
    scenario("next week at 80%: alerts again", 8_000, 10_000, ["80%", "80%"], kinds(await notices(sessions, alex)))


async def test_deleting_and_restoring_an_expense_moves_progress(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    budget = await create_budget(api, alex, "monthly", 10_000)
    await add_personal(api, alex, 6_000, "2025-03-02")
    big = await add_personal(api, alex, 4_500, "2025-03-03")
    assert (await progress(api, alex, budget))["status"] == "exceeded"

    assert (await api.delete(f"/api/v1/expenses/{big['id']}", headers=bearer(alex))).status_code == 200
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["percentUsed"], p["status"]) == (6_000, 60, "under")

    assert (await api.post(f"/api/v1/expenses/{big['id']}/restore", headers=bearer(alex))).status_code == 200
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["status"]) == (10_500, "exceeded")
    # Deleting and restoring within the month never re-sends what was already sent.
    assert await notices(sessions, alex) == [(EXCEEDED, key(budget, "2025-03-01", 100))]


# ==============================================================================
# Shared expenses: the user's share, every affected user checked
# ==============================================================================


async def test_shared_expense_counts_only_the_share_and_an_edit_checks_every_affected_user(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex, blair, casey, group = w["alex"], w["blair"], w["casey"], w["group"]
    budgets = {u.name: await create_budget(api, u, "monthly", 10_000) for u in (alex, blair, casey)}

    # Blair pays ₹160 for Blair and Casey: each SHARE is 8,000 (80%); Blair's cash paid is ignored.
    exp = await add_shared(api, group, blair, 16_000, "2025-03-11", [blair, casey])
    for user, spent, status in ((alex, 0, "under"), (blair, 8_000, "warning"), (casey, 8_000, "warning")):
        p = await progress(api, user, budgets[user.name])
        assert (p["spentPaise"], p["status"]) == (spent, status), user.name
    assert await notices(sessions, blair) == [(WARNING, key(budgets["Blair"], "2025-03-01", 80))]
    assert await notices(sessions, casey) == [(WARNING, key(budgets["Casey"], "2025-03-01", 80))]
    assert await notices(sessions, alex) == []

    # Alex (group admin, not the creator) edits it to ₹300 shared by all three: 10,000 each.
    # Blair and Casey are not the actor, and Alex had no share before: all three are checked.
    exp = await edit_shared(api, group, alex, exp, 30_000, [alex, blair, casey])
    for user in (alex, blair, casey):
        p = await progress(api, user, budgets[user.name])
        assert (p["spentPaise"], p["percentUsed"], p["status"]) == (10_000, 100, "exceeded"), user.name
    assert await notices(sessions, alex) == [(EXCEEDED, key(budgets["Alex"], "2025-03-01", 100))]  # straight past
    assert [k for k, _ in await notices(sessions, blair)] == [WARNING, EXCEEDED]
    assert [k for k, _ in await notices(sessions, casey)] == [WARNING, EXCEEDED]

    # Casey is dropped from the split: Casey's progress falls to 0 straight away.
    exp = await edit_shared(api, group, alex, exp, 10_000, [alex, blair])
    assert (await progress(api, casey, budgets["Casey"]))["spentPaise"] == 0
    assert (await progress(api, blair, budgets["Blair"]))["status"] == "under"

    # Alex deletes it: everyone is back to 0, and nothing more is sent.
    resp = await api.delete(f"/api/v1/groups/{group.id}/expenses/{exp['id']}", headers=bearer(alex))
    assert resp.status_code == 200, resp.text
    for user in (alex, blair, casey):
        assert (await progress(api, user, budgets[user.name]))["spentPaise"] == 0
    assert len(await notices(sessions, blair)) == len(await notices(sessions, casey)) == 2


async def test_settlements_never_change_spending(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex, blair, casey, group = w["alex"], w["blair"], w["casey"], w["group"]
    alex_budget = await create_budget(api, alex, "monthly", 10_000)
    blair_budget = await create_budget(api, blair, "monthly", 10_000)

    await add_shared(api, group, alex, 24_000, "2025-03-05", [alex, blair, casey])  # 8,000 each
    before = (await progress(api, alex, alex_budget), await progress(api, blair, blair_budget))
    assert before[0]["spentPaise"] == before[1]["spentPaise"] == 8_000  # Alex paid 24,000 in cash

    resp = await api.post(
        f"/api/v1/groups/{group.id}/settlements",
        json={"payer_id": str(blair.id), "payee_id": str(alex.id), "amount_paise": 8_000},
        headers=bearer(blair),
    )
    assert resp.status_code == 201, resp.text
    after = (await progress(api, alex, alex_budget), await progress(api, blair, blair_budget))
    assert after == before
    assert [k for k, _ in await notices(sessions, alex)] == [WARNING]
    assert [k for k, _ in await notices(sessions, blair)] == [WARNING]


# ==============================================================================
# Overall vs category, weekly vs monthly
# ==============================================================================


async def test_overall_and_category_budgets_weekly_and_monthly(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    weekly_all = await create_budget(api, alex, "weekly", 10_000)
    weekly_food = await create_budget(api, alex, "weekly", 5_000, FOOD)
    monthly_all = await create_budget(api, alex, "monthly", 50_000)
    monthly_groceries = await create_budget(api, alex, "monthly", 10_000, GROCERIES)

    await add_personal(api, alex, 4_000, "2025-03-11", FOOD)  # this week
    await add_personal(api, alex, 8_000, "2025-03-03", GROCERIES)  # this month, last week
    await add_personal(api, alex, 5_000, "2025-03-12", FOOD)  # this week
    await add_personal(api, alex, 9_999, "2025-02-28", GROCERIES)  # last month: never counts

    expected = {
        weekly_all: (9_000, 90, "warning", "2025-03-10"),
        weekly_food: (9_000, 180, "exceeded", "2025-03-10"),
        monthly_all: (17_000, 34, "under", "2025-03-01"),
        monthly_groceries: (8_000, 80, "warning", "2025-03-01"),
    }
    for budget_id, (spent, pct, status, start) in expected.items():
        p = await progress(api, alex, budget_id)
        assert (p["spentPaise"], p["percentUsed"], p["status"], p["periodStart"]) == (spent, pct, status, start)

    assert await alert_rows(sessions, weekly_all) == [("2025-03-10", 80, False)]
    # Food went 0% -> 80% (4,000 of 5,000) -> 180%: the 80% alert, then the 100% alert.
    assert await alert_rows(sessions, weekly_food) == [("2025-03-10", 80, False), ("2025-03-10", 100, False)]
    assert await alert_rows(sessions, monthly_all) == []
    assert await alert_rows(sessions, monthly_groceries) == [("2025-03-01", 80, False)]
    assert sorted(await notices(sessions, alex)) == sorted([
        (WARNING, key(weekly_all, "2025-03-10", 80)),
        (WARNING, key(weekly_food, "2025-03-10", 80)),
        (EXCEEDED, key(weekly_food, "2025-03-10", 100)),
        (WARNING, key(monthly_groceries, "2025-03-01", 80)),
    ])

    listed = (await api.get("/api/v1/budgets", headers=bearer(alex))).json()
    # The fake clock gives every budget the same created_at, so only membership is compared here.
    assert sorted(b["id"] for b in listed["data"]) == sorted([weekly_all, weekly_food, monthly_all, monthly_groceries])
    assert {b["id"]: b["progress"]["spentPaise"] for b in listed["data"]} == {k: v[0] for k, v in expected.items()}
    assert listed["meta"]["total"] == 4


# ==============================================================================
# Concurrency: exactly one alert and one notification
# ==============================================================================


async def test_two_concurrent_saves_crossing_80_make_one_alert_and_one_notification(pg):
    api, sessions = pg["api"], pg["sessions"]
    for _ in range(5):  # several fresh users, to give the race real chances
        w = await seed(sessions)
        alex = w["alex"]
        budget = await create_budget(api, alex, "monthly", 10_000)
        await add_personal(api, alex, 7_500, "2025-03-01")

        async def save(amount: int) -> None:
            async with sessions() as s:
                await expense_service.create_expense(
                    s, alex.id,
                    ExpenseCreate(amount_paise=amount, description="Race", category_id=FOOD, expense_date=D("2025-03-12")),
                )

        await asyncio.gather(save(500), save(600))  # each alone reaches 80%; together 86%
        assert (await progress(api, alex, budget))["spentPaise"] == 8_600
        assert await alert_rows(sessions, budget) == [("2025-03-01", 80, False)]
        assert await notices(sessions, alex) == [(WARNING, key(budget, "2025-03-01", 80))]


async def test_many_concurrent_checks_never_duplicate(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    budget = await create_budget(api, alex, "monthly", 10_000)
    # Spending written straight to the table (no hook), then 12 checks at the same time.
    now = datetime.now(UTC)
    async with sessions() as s:
        s.add(Expense(id=uuid.uuid4(), user_id=alex.id, group_id=None, category_id=FOOD, amount_minor=12_000,
                      description="Direct", expense_date=D("2025-03-12"), version=1,
                      created_at=now, updated_at=now, deleted_at=None))
        await s.commit()
    await asyncio.gather(*(budget_service.check_after_commit([alex.id]) for _ in range(12)))
    assert await alert_rows(sessions, budget) == [("2025-03-01", 80, True), ("2025-03-01", 100, False)]
    assert await notices(sessions, alex) == [(EXCEEDED, key(budget, "2025-03-01", 100))]


# ==============================================================================
# Recurring-generated expenses, limit changes, preferences
# ==============================================================================


async def test_a_recurring_generated_expense_triggers_the_check(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    budget = await create_budget(api, alex, "monthly", 10_000)
    async with sessions() as s:
        await recurring_service.create_rule(
            s, await s.get(User, alex.id),
            RecurringRuleCreate(frequency="monthly", start_date=D("2025-03-12"), amount_paise=8_000,
                                category_id=FOOD, description="Rent share"),
        )
    stats = await recurring_service.run_due(user_id=alex.id)
    assert stats.created == 1
    p = await progress(api, alex, budget)
    assert (p["spentPaise"], p["status"]) == (8_000, "warning")
    assert await notices(sessions, alex) == [(WARNING, key(budget, "2025-03-01", 80))]


async def test_lowering_the_limit_alerts_at_once_and_raising_it_never_unsends(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    budget = await create_budget(api, alex, "monthly", 20_000)
    await add_personal(api, alex, 9_000, "2025-03-04")
    assert await notices(sessions, alex) == []

    async def set_limit(limit: int) -> dict[str, Any]:
        resp = await api.patch(f"/api/v1/budgets/{budget}", json={"limitPaise": limit}, headers=bearer(alex))
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    assert (await set_limit(10_000))["progress"]["status"] == "warning"  # 90%: alerts now
    assert await notices(sessions, alex) == [(WARNING, key(budget, "2025-03-01", 80))]
    assert (await set_limit(100_000))["progress"]["status"] == "under"  # 9%: nothing taken back
    assert await alert_rows(sessions, budget) == [("2025-03-01", 80, False)]
    assert (await set_limit(10_000))["progress"]["status"] == "warning"  # no second 80% alert
    assert (await set_limit(9_000))["progress"]["status"] == "exceeded"  # 100%: the 100% alert
    assert [k for k, _ in await notices(sessions, alex)] == [WARNING, EXCEEDED]


async def test_a_budget_created_over_80_percent_alerts_at_once(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    casey = w["casey"]
    await add_personal(api, casey, 4_500, "2025-03-12")
    budget = await create_budget(api, casey, "weekly", 5_000)
    assert await notices(sessions, casey) == [(WARNING, key(budget, "2025-03-10", 80))]


async def test_switched_off_kind_records_the_alert_but_sends_nothing(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    resp = await api.put(
        "/api/v1/notification-preferences",
        json={"preferences": [{"kind": WARNING, "enabled": False}]},
        headers=bearer(alex),
    )
    assert resp.status_code == 200, resp.text
    budget = await create_budget(api, alex, "monthly", 10_000)
    await add_personal(api, alex, 8_000, "2025-03-12")
    assert await alert_rows(sessions, budget) == [("2025-03-01", 80, False)]
    assert await notices(sessions, alex) == []
    await add_personal(api, alex, 2_000, "2025-03-12")
    assert await notices(sessions, alex) == [(EXCEEDED, key(budget, "2025-03-01", 100))]


# ==============================================================================
# API rules and database constraints
# ==============================================================================


async def test_api_owner_only_duplicates_and_soft_delete(pg):
    api, sessions = pg["api"], pg["sessions"]
    w = await seed(sessions)
    alex, sam = w["alex"], w["sam"]
    budget = await create_budget(api, alex, "monthly", 10_000)

    for method, body in (("GET", None), ("PATCH", {"limitPaise": 1}), ("DELETE", None)):
        resp = await api.request(method, f"/api/v1/budgets/{budget}", json=body, headers=bearer(sam))
        assert resp.status_code == 404 and resp.json()["code"] == "BUDGET_NOT_FOUND"
    assert (await api.get("/api/v1/budgets", headers=bearer(sam))).json()["data"] == []
    assert (await api.get("/api/v1/budgets")).status_code == 401

    dup = await api.post("/api/v1/budgets", json={"period": "monthly", "limitPaise": 5}, headers=bearer(alex))
    assert dup.status_code == 409 and dup.json()["code"] == "BUDGET_EXISTS"

    # Two identical creates at the same moment: the partial unique index lets only one win.
    async def post() -> int:
        r = await api.post("/api/v1/budgets", json={"period": "weekly", "limitPaise": 5, "categoryId": str(FOOD)},
                           headers=bearer(alex))
        return r.status_code

    assert sorted(await asyncio.gather(post(), post())) == [201, 409]

    assert (await api.delete(f"/api/v1/budgets/{budget}", headers=bearer(alex))).status_code == 204
    assert (await api.get(f"/api/v1/budgets/{budget}", headers=bearer(alex))).status_code == 404
    again = await create_budget(api, alex, "monthly", 7_000)
    assert again != budget
    async with sessions() as s:
        rows = (await s.execute(select(Budget).where(Budget.user_id == alex.id, Budget.period == "monthly"))).scalars().all()
        assert sorted((b.limit_paise, b.deleted_at is None) for b in rows) == [(7_000, True), (10_000, False)]

    replay_headers = {**bearer(alex), "Idempotency-Key": "t48-create"}
    body = {"period": "weekly", "limitPaise": 3_000}
    first = await api.post("/api/v1/budgets", json=body, headers=replay_headers)
    replay = await api.post("/api/v1/budgets", json=body, headers=replay_headers)
    assert first.status_code == replay.status_code == 201
    assert replay.headers.get("X-Idempotent-Replay") == "true"
    assert replay.json()["data"]["id"] == first.json()["data"]["id"]


async def test_database_constraints(pg):
    sessions = pg["sessions"]
    w = await seed(sessions)
    alex = w["alex"]
    now = datetime.now(UTC)

    def budget(**fields: Any) -> Budget:
        base = dict(id=uuid.uuid4(), user_id=alex.id, period="monthly", category_id=None, limit_paise=100,
                    created_at=now, updated_at=now, deleted_at=None)
        return Budget(**{**base, **fields})

    for bad in (budget(limit_paise=0), budget(limit_paise=-1), budget(period="daily")):
        async with sessions() as s:
            s.add(bad)
            with pytest.raises(IntegrityError):
                await s.commit()

    first = budget()
    async with sessions() as s:
        s.add_all([first, budget(category_id=FOOD), budget(period="weekly"), budget(deleted_at=now)])
        await s.commit()
    for dup in (budget(), budget(category_id=FOOD)):
        async with sessions() as s:
            s.add(dup)
            with pytest.raises(IntegrityError):
                await s.commit()

    def alert(**fields: Any) -> BudgetAlert:
        base = dict(id=uuid.uuid4(), budget_id=first.id, period_start=D("2025-03-01"), period_end=D("2025-03-31"),
                    threshold=80, spent_paise=80, limit_paise=100, suppressed=False, created_at=now)
        return BudgetAlert(**{**base, **fields})

    async with sessions() as s:
        s.add(alert())
        await s.commit()
    for bad_alert in (alert(), alert(threshold=50), alert(period_end=D("2025-02-28")), alert(threshold=100, spent_paise=-1)):
        async with sessions() as s:
            s.add(bad_alert)
            with pytest.raises(IntegrityError):
                await s.commit()
    async with sessions() as s:  # another period or threshold is a separate alert
        s.add_all([alert(threshold=100), alert(period_start=D("2025-04-01"), period_end=D("2025-04-30"))])
        await s.commit()
