"""Real-PostgreSQL checks for recurring expenses (US-14 / T-44).

T-44 Done-when: "90 simulated days with restarts create zero duplicates."

The module builds ONE throwaway database with ``alembic upgrade head`` (so the real 015
migration, its UNIQUE key, CHECKs and deferred foreign key are what is tested), runs every
test against it with its own users, and drops it at the end. The generator, the
notification centre and the create services all run for real; only the clock is fake.

SKIPPED when no local PostgreSQL is reachable. Same rules as the other *_pg.py files:
COINSCIOUS_TEST_PG_URL is an admin URL on a LOCAL server (default
postgresql+asyncpg://postgres:postgres@localhost:5432/postgres); any other host is refused.
"""

from __future__ import annotations

import asyncio
import os
import random
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.category import Category
from app.models.expense import Expense, ExpensePayment, ExpenseShare
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus, GroupType
from app.models.notification import Notification
from app.models.recurring import RecurringOccurrence, RecurringRule
from app.models.user import User
from app.schemas.recurring import RecurringRuleCreate, RecurringRuleUpdate
from app.services import analytics_service, notifications, recurring_service
from app.services import expenses as expense_service
from app.services.notifications import _persist as real_persist
from app.services.notifications import active_member_roles as real_active_member_roles

DEFAULT_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
ADMIN_URL = os.getenv("COINSCIOUS_TEST_PG_URL", DEFAULT_ADMIN_URL)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
BACKEND_DIR = Path(__file__).resolve().parent.parent
D = date.fromisoformat
UPCOMING = "recurring_expense_upcoming"
SKIPPED = "recurring_expense_skipped"


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
    name = f"coinscious_t44_{uuid.uuid4().hex[:12]}"
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # noqa: BLE001 - any connection problem means "no Postgres here"
        admin.dispose()
        pytest.skip(
            "No local PostgreSQL reachable at "
            f"{admin_url.render_as_string(hide_password=True)} ({type(exc).__name__}); "
            "T-44 Done-when not verified on a real database. Set COINSCIOUS_TEST_PG_URL to run."
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
        assert "015_recurring_expenses" in output
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
    """Real sessions for the generator, the notification centre and the create services."""
    engine = create_async_engine(migrated_db, pool_size=10, max_overflow=10)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    clock = {"now": ist("2024-01-01T10:00:00")}
    monkeypatch.setattr(recurring_service, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(recurring_service, "_now", lambda: clock["now"])
    monkeypatch.setattr(notifications, "AsyncSessionLocal", sessions)
    monkeypatch.setattr(notifications, "_persist", real_persist)
    monkeypatch.setattr(notifications, "active_member_roles", real_active_member_roles)
    # run_due() without a user scans every rule: start each test with none left from
    # earlier tests (their occurrences cascade; their expenses stay, tests filter by owner).
    async with sessions() as s:
        await s.execute(text("DELETE FROM recurring_rules"))
        await s.commit()
    try:
        yield {"engine": engine, "sessions": sessions, "clock": clock}
    finally:
        await engine.dispose()


async def seed(sessions: async_sessionmaker[AsyncSession], members: int = 3) -> dict[str, Any]:
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    users = [
        User(id=uuid.uuid4(), email=f"{n}-{tag}@example.com", name=n.title(),
             hashed_password=hash_password("Correct-Horse-Battery-9"), is_active=True)
        for n in ("alex", "blair", "casey", "drew")[:members]
    ]
    category = Category(id=uuid.uuid4(), name=f"Bills {tag}", is_default=True)
    group = Group(id=uuid.uuid4(), name=f"Flat {tag}", type=GroupType.FLAT.value,
                  created_by=users[0].id, created_at=now, updated_at=now)
    async with sessions() as s:
        s.add_all([*users, category, group])
        await s.flush()
        for i, u in enumerate(users):
            s.add(GroupMember(
                group_id=group.id, user_id=u.id,
                role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
                status=GroupMemberStatus.ACTIVE.value, joined_at=now + timedelta(seconds=i), updated_at=now,
            ))
        await s.commit()
    return {"users": users, "category": category, "group": group}


async def create_rule(sessions, owner: User, **fields: Any) -> uuid.UUID:
    async with sessions() as s:
        row = await s.get(User, owner.id)
        response, _ = await recurring_service.create_rule(s, row, RecurringRuleCreate(**fields))
    return response.id


async def change(sessions, owner: User, rule_id: uuid.UUID, action: str) -> None:
    async with sessions() as s:
        await recurring_service.change_status(s, await s.get(User, owner.id), rule_id, action)  # type: ignore[arg-type]


async def scalars(sessions, stmt) -> list[Any]:
    async with sessions() as s:
        return list((await s.execute(stmt)).scalars().all())


async def occurrence_dates(sessions, rule_id: uuid.UUID, state: str = "created") -> list[date]:
    return await scalars(
        sessions,
        select(RecurringOccurrence.occurrence_date)
        .where(RecurringOccurrence.rule_id == rule_id, RecurringOccurrence.status == state)
        .order_by(RecurringOccurrence.occurrence_date),
    )


async def notice_keys(sessions, user_id: uuid.UUID, kind: str = UPCOMING) -> list[str]:
    return await scalars(
        sessions, select(Notification.dedupe_key).where(Notification.user_id == user_id, Notification.kind == kind)
    )


def weekly(first: str, last: str) -> list[date]:
    out, d = [], D(first)
    while d <= D(last):
        out.append(d)
        d += timedelta(days=7)
    return out


def daily(first: str, last: str) -> list[date]:
    return [D(first) + timedelta(days=i) for i in range((D(last) - D(first)).days + 1)]


async def restart_server() -> None:
    """A process restart: the lifespan task starts, does its startup catch-up, then the
    process dies (task cancelled)."""
    before = recurring_service.scheduler_runs
    task = recurring_service.start_scheduler(interval_seconds=3600)
    for _ in range(3000):
        if recurring_service.scheduler_runs > before:
            break
        await asyncio.sleep(0.01)
    await recurring_service.stop_scheduler(task)
    assert recurring_service.scheduler_runs > before, "startup catch-up did not finish"


# ==============================================================================
# T-44 DONE-WHEN: 90 simulated days with restarts create zero duplicates
# ==============================================================================


async def test_done_when_90_days_hourly_with_restarts_logins_and_concurrent_runs(pg, monkeypatch, capsys):
    sessions, clock = pg["sessions"], pg["clock"]
    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_TIMEOUT_SECONDS", 30.0)
    world = await seed(sessions, members=1)
    owner, cat = world["users"][0], world["category"].id
    start = ist("2024-01-01T10:00:00")
    clock["now"] = start

    base = dict(category_id=cat, amount_paise=10_000)
    rules = {
        "daily": await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"), description="daily", **base),
        "weekly": await create_rule(sessions, owner, frequency="weekly", start_date=D("2024-01-03"), description="weekly", **base),
        "monthly31": await create_rule(sessions, owner, frequency="monthly", start_date=D("2024-01-31"), description="monthly31", **base),
        "paused": await create_rule(sessions, owner, frequency="weekly", start_date=D("2024-01-03"), description="paused", **base),
        "cancelled": await create_rule(sessions, owner, frequency="weekly", start_date=D("2024-01-04"), description="cancelled", **base),
        "ended": await create_rule(sessions, owner, frequency="weekly", start_date=D("2024-01-05"),
                                   end_date=D("2024-02-20"), description="ended", **base),
    }
    expected = {
        "daily": daily("2024-01-02", "2024-03-31"),
        "weekly": weekly("2024-01-03", "2024-03-31"),
        "monthly31": [D("2024-01-31"), D("2024-02-29"), D("2024-03-31")],
        "paused": [d for d in weekly("2024-01-03", "2024-03-31") if d not in (D("2024-01-24"), D("2024-01-31"))],
        "cancelled": weekly("2024-01-04", "2024-02-08"),
        "ended": weekly("2024-01-05", "2024-02-20"),
    }
    events = {
        ist("2024-01-19T10:00:00"): ("paused", "pause"),    # next is 24 Jan: no notice sent yet
        ist("2024-02-02T10:00:00"): ("paused", "resume"),   # continues 7 Feb, no back-fill
        ist("2024-02-10T10:00:00"): ("cancelled", "cancel"),
    }

    rng = random.Random(44)
    hours = 90 * 24
    down_until = -1
    last_restart = -100
    figures = Counter()
    for h in range(hours + 1):
        clock["now"] = start + timedelta(hours=h)
        if clock["now"] in events:
            name, action = events[clock["now"]]
            await change(sessions, owner, rules[name], action)
        if h <= down_until:
            continue  # the free server is asleep: no hourly run
        if h - last_restart > 24 and rng.random() < 0.04:
            # The server goes down for 2-7 hours (this hour included), then restarts and
            # runs its startup catch-up. Restarts are >= 24 h apart, so every Kolkata day
            # still has hourly runs for the 24-hour notices.
            down_until = h + rng.randint(1, 6)
            last_restart = down_until
            figures["downtime_hours"] += down_until - h + 1
            continue
        if h == last_restart + 1 and h > 1:
            await restart_server()
            figures["restarts"] += 1
        if clock["now"].astimezone(recurring_service.IST).hour == 0:
            # Midnight in Kolkata, when occurrences fall due: two generator runs AND a
            # login catch-up at the same time.
            await asyncio.gather(
                recurring_service.run_due(), recurring_service.run_due(),
                recurring_service.catch_up_after_login(owner.id),
            )
            figures["concurrent_batches"] += 1
            figures["runs"] += 2
            figures["login_catchups"] += 1
        else:
            await recurring_service.run_due()
            figures["runs"] += 1
            if rng.random() < 0.03:
                await recurring_service.catch_up_after_login(owner.id)
                figures["login_catchups"] += 1

    # --- exactly one expense per (rule, occurrence date), the right dates --------------
    created_total = 0
    for name, rule_id in rules.items():
        got = await occurrence_dates(sessions, rule_id)
        assert got == expected[name], name
        assert await occurrence_dates(sessions, rule_id, "skipped") == []
        created_total += len(got)
    expected_total = sum(len(v) for v in expected.values())
    assert created_total == expected_total == 130

    async with sessions() as s:
        dup_occurrences = (await s.execute(
            select(func.count()).select_from(
                select(RecurringOccurrence.rule_id, RecurringOccurrence.occurrence_date)
                .group_by(RecurringOccurrence.rule_id, RecurringOccurrence.occurrence_date)
                .having(func.count() > 1).subquery()
            )
        )).scalar_one()
        rows = (await s.execute(
            select(RecurringOccurrence.occurrence_date, Expense.expense_date, Expense.description,
                   Expense.amount_minor, Expense.user_id, Expense.deleted_at)
            .join(Expense, Expense.id == RecurringOccurrence.expense_id)
            .where(RecurringOccurrence.rule_id.in_(list(rules.values())))
        )).all()
        expense_count = (await s.execute(
            select(func.count(Expense.id)).where(Expense.user_id == owner.id)
        )).scalar_one()
        dup_expenses = (await s.execute(
            select(func.count()).select_from(
                select(Expense.description, Expense.expense_date)
                .where(Expense.user_id == owner.id)
                .group_by(Expense.description, Expense.expense_date)
                .having(func.count() > 1).subquery()
            )
        )).scalar_one()
        final = {r.description: r for r in (await s.execute(
            select(RecurringRule).where(RecurringRule.owner_id == owner.id))).scalars()}
    assert dup_occurrences == 0 and dup_expenses == 0
    assert expense_count == expected_total == len(rows)  # no expense without its occurrence
    assert all(r.occurrence_date == r.expense_date for r in rows)
    assert all(r.amount_minor == 10_000 and r.user_id == owner.id and r.deleted_at is None for r in rows)

    # --- exactly one 24-hour notice per occurrence, none for paused/cancelled/ended dates --
    keys = await notice_keys(sessions, owner.id)
    expected_keys = {
        f"{UPCOMING}:{rules[name]}:{d.isoformat()}" for name, dates in expected.items() for d in dates
    }
    # The simulation ends at 31 Mar 10:00 IST: the daily rule's 1 Apr occurrence is not due
    # yet, but its 24-hour notice was (from 31 Mar 00:00). No other rule is due on 1 Apr.
    pending = f"{UPCOMING}:{rules['daily']}:2024-04-01"
    expected_keys.add(pending)
    assert len(keys) == len(set(keys)) == len(expected_keys)
    assert set(keys) == expected_keys

    assert final["paused"].status == "active" and final["cancelled"].status == "cancelled"
    assert final["cancelled"].next_run_date is None and final["ended"].next_run_date is None
    assert final["monthly31"].next_run_date == D("2024-04-30")
    assert final["daily"].next_run_date == D("2024-04-01")
    assert figures["restarts"] >= 3 and figures["concurrent_batches"] >= 60

    with capsys.disabled():
        print(
            f"\n[T-44 done-when] days=90 rules={len(rules)} expected={expected_total} created={created_total} "
            f"duplicates={dup_occurrences + dup_expenses} notices={len(keys)} (expected {len(expected_keys)}) "
            f"generator_runs={figures['runs']} concurrent_batches={figures['concurrent_batches']} "
            f"restarts={figures['restarts']} downtime_hours={figures['downtime_hours']} "
            f"login_catchups={figures['login_catchups']}"
        )


# ==============================================================================
# Catch-up, limits, concurrency
# ==============================================================================


async def test_catch_up_after_a_long_gap_creates_every_missed_date_with_its_own_date(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"),
                                amount_paise=5_000, category_id=world["category"].id, description="gap")
    clock["now"] = ist("2024-03-01T09:00:00")  # nothing ran for two months
    stats = await recurring_service.run_due()
    assert stats.created == 60
    assert await occurrence_dates(sessions, rule_id) == daily("2024-01-02", "2024-03-01")
    dates = await scalars(sessions, select(Expense.expense_date).where(Expense.user_id == owner.id)
                          .order_by(Expense.expense_date))
    assert dates == daily("2024-01-02", "2024-03-01")
    # No late "upcoming" notices for dates already past; only tomorrow's.
    assert await notice_keys(sessions, owner.id) == [f"{UPCOMING}:{rule_id}:2024-03-02"]
    assert (await recurring_service.run_due()).created == 0


async def test_safety_limit_per_run_and_the_next_run_finishes(pg, monkeypatch):
    sessions, clock = pg["sessions"], pg["clock"]
    monkeypatch.setattr(settings, "RECURRING_MAX_OCCURRENCES_PER_RULE_PER_RUN", 10)
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"),
                                amount_paise=5_000, category_id=world["category"].id, description="limited")
    clock["now"] = ist("2024-01-25T09:00:00")
    assert (await recurring_service.run_due()).created == 10
    assert (await recurring_service.run_due()).created == 10
    assert (await recurring_service.run_due()).created == 4
    assert await occurrence_dates(sessions, rule_id) == daily("2024-01-02", "2024-01-25")


async def test_many_concurrent_runs_create_each_occurrence_exactly_once(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    ids = [
        await create_rule(sessions, owner, frequency=f, start_date=D("2024-01-02"), amount_paise=700,
                          category_id=world["category"].id, description=f"race-{f}")
        for f in ("daily", "weekly")
    ]
    clock["now"] = ist("2024-01-31T12:00:00")
    results = await asyncio.gather(
        *[recurring_service.run_due() for _ in range(6)],
        *[recurring_service.run_due(user_id=owner.id) for _ in range(4)],
    )
    assert sum(r.created for r in results) == 30 + 5
    assert await occurrence_dates(sessions, ids[0]) == daily("2024-01-02", "2024-01-31")
    assert await occurrence_dates(sessions, ids[1]) == weekly("2024-01-02", "2024-01-31")
    count = await scalars(sessions, select(func.count(Expense.id)).where(Expense.user_id == owner.id))
    assert count == [35]


# ==============================================================================
# Pause / resume / edit / delete semantics on the real generator
# ==============================================================================


async def test_paused_rule_gets_nothing_and_resumed_rule_only_future_notices(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"),
                                amount_paise=100, category_id=world["category"].id, description="pausable")
    await recurring_service.run_due()                      # notice for 2 Jan
    await change(sessions, owner, rule_id, "pause")
    for day in range(2, 6):
        clock["now"] = ist(f"2024-01-0{day}T12:00:00")
        await recurring_service.run_due()
    assert await occurrence_dates(sessions, rule_id) == []
    clock["now"] = ist("2024-01-05T12:00:00")
    await change(sessions, owner, rule_id, "resume")      # continues today (5 Jan), no back-fill
    await recurring_service.run_due()
    assert await occurrence_dates(sessions, rule_id) == [D("2024-01-05")]
    assert sorted(await notice_keys(sessions, owner.id)) == [
        f"{UPCOMING}:{rule_id}:2024-01-02",  # sent before the pause
        f"{UPCOMING}:{rule_id}:2024-01-06",  # after resuming: future dates only
    ]


async def test_edit_changes_only_future_occurrences(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"),
                                amount_paise=1_000, category_id=world["category"].id, description="before edit")
    clock["now"] = ist("2024-01-04T12:00:00")
    await recurring_service.run_due()
    async with sessions() as s:
        await recurring_service.update_rule(
            s, await s.get(User, owner.id), rule_id,
            RecurringRuleUpdate(amount_paise=2_500, description="after edit", end_date=D("2024-01-06")),
        )
    clock["now"] = ist("2024-01-10T12:00:00")
    await recurring_service.run_due()
    async with sessions() as s:
        rows = (await s.execute(select(Expense.expense_date, Expense.amount_minor, Expense.description)
                                .where(Expense.user_id == owner.id).order_by(Expense.expense_date))).all()
    assert [(r.expense_date.day, r.amount_minor, r.description) for r in rows] == [
        (2, 1_000, "before edit"), (3, 1_000, "before edit"), (4, 1_000, "before edit"),
        (5, 2_500, "after edit"), (6, 2_500, "after edit"),
    ]


async def test_deleted_generated_expenses_are_never_recreated(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"),
                                amount_paise=1_000, category_id=world["category"].id, description="deletable")
    clock["now"] = ist("2024-01-04T12:00:00")
    await recurring_service.run_due()
    async with sessions() as s:
        occ = {o.occurrence_date: o for o in (await s.execute(
            select(RecurringOccurrence).where(RecurringOccurrence.rule_id == rule_id))).scalars()}
    async with sessions() as s:
        await expense_service.soft_delete_expense(s, owner.id, occ[D("2024-01-02")].expense_id)
    async with sessions() as s:
        await expense_service.hard_delete_expense(s, owner.id, occ[D("2024-01-03")].expense_id)
    # Even if the rule were wound back to the first date, handled dates are only skipped over.
    async with sessions() as s:
        await s.execute(update(RecurringRule).where(RecurringRule.id == rule_id).values(next_run_date=D("2024-01-02")))
        await s.commit()
    clock["now"] = ist("2024-01-05T12:00:00")
    for _ in range(3):
        await recurring_service.run_due()
    async with sessions() as s:
        live = (await s.execute(select(Expense.expense_date).where(
            Expense.user_id == owner.id, Expense.deleted_at.is_(None)).order_by(Expense.expense_date))).scalars().all()
        hard = await s.get(RecurringOccurrence, occ[D("2024-01-03")].id)
    assert live == [D("2024-01-04"), D("2024-01-05")]
    assert hard.status == "created" and hard.expense_id is None  # FK ON DELETE SET NULL keeps the row
    assert await occurrence_dates(sessions, rule_id) == daily("2024-01-02", "2024-01-05")


# ==============================================================================
# Group rules
# ==============================================================================


async def test_group_rule_creates_shared_expenses_and_skips_when_a_participant_left(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=3)
    alex, blair, casey = world["users"]
    group = world["group"]
    rule_id = await create_rule(
        sessions, alex, frequency="monthly", start_date=D("2024-01-31"), amount_paise=100_000,
        category_id=world["category"].id, description="Rent", group_id=group.id,
        split={"paid_by_user_id": alex.id, "participant_user_ids": [alex.id, blair.id, casey.id]},
    )
    clock["now"] = ist("2024-01-31T08:00:00")
    assert (await recurring_service.run_due()).created == 1
    async with sessions() as s:
        (occ,) = (await s.execute(select(RecurringOccurrence).where(RecurringOccurrence.rule_id == rule_id))).scalars()
        expense = await s.get(Expense, occ.expense_id)
        shares = (await s.execute(select(ExpenseShare.amount_paise).where(ExpenseShare.expense_id == expense.id))).scalars().all()
        payments = (await s.execute(select(ExpensePayment.user_id, ExpensePayment.amount_paise)
                                    .where(ExpensePayment.expense_id == expense.id))).all()
    assert expense.group_id == group.id and expense.expense_date == D("2024-01-31")
    assert sorted(shares) == [33_333, 33_333, 33_334] and sum(shares) == 100_000  # ledger allocation
    assert [(p.user_id, p.amount_paise) for p in payments] == [(alex.id, 100_000)]
    # Existing notification rules: the other members hear about the new group expense.
    for member in (blair, casey):
        assert await notice_keys(sessions, member.id, "group_expense_created") == [
            f"group_expense_created:{expense.id}:{member.id}"
        ]

    async with sessions() as s:
        await s.execute(update(GroupMember).where(GroupMember.group_id == group.id, GroupMember.user_id == casey.id)
                        .values(status=GroupMemberStatus.LEFT.value))
        await s.commit()
    clock["now"] = ist("2024-03-31T08:00:00")
    stats = await recurring_service.run_due()
    assert stats.created == 0 and stats.skipped == 2
    async with sessions() as s:
        skipped = (await s.execute(select(RecurringOccurrence).where(
            RecurringOccurrence.rule_id == rule_id, RecurringOccurrence.status == "skipped")
            .order_by(RecurringOccurrence.occurrence_date))).scalars().all()
        n_expenses = (await s.execute(select(func.count(Expense.id)).where(Expense.group_id == group.id))).scalar_one()
    assert [(o.occurrence_date, o.skip_reason, o.expense_id) for o in skipped] == [
        (D("2024-02-29"), "PARTICIPANT_NOT_MEMBER", None), (D("2024-03-31"), "PARTICIPANT_NOT_MEMBER", None),
    ]
    assert n_expenses == 1
    assert sorted(await notice_keys(sessions, alex.id, SKIPPED)) == [
        f"{SKIPPED}:{rule_id}:2024-02-29", f"{SKIPPED}:{rule_id}:2024-03-31",
    ]
    assert (await recurring_service.run_due()).skipped == 0  # recorded once, never retried


async def test_group_rule_validation_uses_the_shared_expense_rules(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=3)
    alex, blair, casey = world["users"]
    outsider = (await seed(sessions, members=1))["users"][0]
    group, cat = world["group"], world["category"].id
    common = dict(frequency="monthly", start_date=D("2024-01-31"), amount_paise=900, category_id=cat,
                  description="Wifi", group_id=group.id)

    async def attempt(owner: User, **fields: Any) -> tuple[int, str]:
        try:
            await create_rule(sessions, owner, **{**common, **fields})
        except HTTPException as exc:
            return exc.status_code, exc.detail["code"]
        return 201, "CREATED"

    assert await attempt(outsider) == (404, "GROUP_NOT_FOUND")
    assert await attempt(alex, split={"paid_by_user_id": outsider.id}) == (400, "PAYER_NOT_MEMBER")
    assert await attempt(alex, split={"participant_user_ids": [alex.id, outsider.id]}) == (400, "PARTICIPANT_NOT_MEMBER")
    assert await attempt(alex, split={"payments": {str(alex.id): 500, str(blair.id): 300}}) == (400, "UNBALANCED_PAYMENTS")
    bad_exact = {"split_mode": "exact", "participant_user_ids": [alex.id, blair.id],
                 "split_weights": {str(alex.id): 500, str(blair.id): 300}}
    status_code, code = await attempt(alex, split=bad_exact)
    assert status_code == 400 and code in ("INVALID_SPLIT", "UNBALANCED_SHARES")
    good_exact = {"split_mode": "exact", "participant_user_ids": [alex.id, blair.id],
                  "split_weights": {str(alex.id): 600, str(blair.id): 300}}
    assert await attempt(alex, split=good_exact) == (201, "CREATED")

    rule_id = (await scalars(sessions, select(RecurringRule.id).where(RecurringRule.owner_id == alex.id)))[0]
    async with sessions() as s:
        owner = await s.get(User, alex.id)
        for change_ in (RecurringRuleUpdate(amount_paise=1_000),
                        RecurringRuleUpdate(split={"split_mode": "exact", "participant_user_ids": [alex.id, casey.id],
                                                   "split_weights": {str(alex.id): 1, str(casey.id): 1}})):
            with pytest.raises(HTTPException) as exc:
                await recurring_service.update_rule(s, owner, rule_id, change_)
            assert exc.value.status_code == 400
            await s.rollback()
            owner = await s.get(User, alex.id)  # the rollback expired the loaded row
        # amount and split changed together, consistently: accepted
        updated = await recurring_service.update_rule(
            s, owner, rule_id,
            RecurringRuleUpdate(amount_paise=1_000, split={"split_mode": "exact", "participant_user_ids": [alex.id, casey.id],
                                                          "split_weights": {str(alex.id): 400, str(casey.id): 600}}),
        )
    assert updated.amount_paise == 1_000 and updated.split.participant_user_ids == [alex.id, casey.id]


# ==============================================================================
# Analytics, login, API, constraints
# ==============================================================================


async def test_generated_expenses_count_in_analytics_like_normal_expenses(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    await create_rule(sessions, owner, frequency="weekly", start_date=D("2024-01-02"), amount_paise=12_345,
                      category_id=world["category"].id, description="gym")
    clock["now"] = ist("2024-01-31T12:00:00")
    await recurring_service.run_due()
    async with sessions() as s:
        summary = await analytics_service.get_summary(s, await s.get(User, owner.id), D("2024-01-01"), D("2024-01-31"))
    assert summary.expense_count == 5
    assert summary.share_paise == summary.cash_paid_paise == 5 * 12_345  # personal: share = cash paid = amount


async def test_login_catches_up_the_users_rules_end_to_end(pg, monkeypatch):
    sessions, clock = pg["sessions"], pg["clock"]
    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_ENABLED", True)
    world = await seed(sessions, members=1)
    owner = world["users"][0]
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"), amount_paise=100,
                                category_id=world["category"].id, description="login")
    clock["now"] = ist("2024-01-08T09:00:00")

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            resp = await client.post("/api/v1/auth/login",
                                     json={"email": owner.email, "password": "Correct-Horse-Battery-9"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert await occurrence_dates(sessions, rule_id) == daily("2024-01-02", "2024-01-08")


async def test_api_end_to_end_with_idempotency_and_occurrence_history(pg):
    sessions, clock = pg["sessions"], pg["clock"]
    world = await seed(sessions, members=2)
    alex, blair = world["users"]
    headers = {"Authorization": f"Bearer {create_access_token(alex.id, email=alex.email)}"}
    other = {"Authorization": f"Bearer {create_access_token(blair.id, email=blair.email)}"}

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            body = {"frequency": "daily", "startDate": "2024-01-02", "amountPaise": 4_200,
                    "categoryId": str(world["category"].id), "description": "Milk"}
            first = await client.post("/api/v1/recurring", json=body, headers={**headers, "Idempotency-Key": "milk-1"})
            again = await client.post("/api/v1/recurring", json=body, headers={**headers, "Idempotency-Key": "milk-1"})
            assert first.status_code == 201 and again.status_code == 201
            assert again.headers["X-Idempotent-Replay"] == "true"
            rule_id = first.json()["data"]["id"]
            assert again.json()["data"]["id"] == rule_id
            listed = (await client.get("/api/v1/recurring", headers=headers)).json()
            assert listed["meta"]["total"] == 1 and listed["data"][0]["nextRunDate"] == "2024-01-02"

            clock["now"] = ist("2024-01-03T12:00:00")
            await recurring_service.run_due()
            history = (await client.get(f"/api/v1/recurring/{rule_id}/occurrences", headers=headers)).json()
            assert [o["occurrenceDate"] for o in history["data"]] == ["2024-01-03", "2024-01-02"]
            assert all(o["status"] == "created" and o["expenseId"] for o in history["data"])
            expense = await client.get(f"/api/v1/expenses/{history['data'][0]['expenseId']}", headers=headers)
            assert expense.status_code == 200 and expense.json()["data"]["expenseDate"] == "2024-01-03"

            for path in (f"/api/v1/recurring/{rule_id}", f"/api/v1/recurring/{rule_id}/occurrences"):
                assert (await client.get(path, headers=other)).status_code == 404
            assert (await client.post(f"/api/v1/recurring/{rule_id}/cancel", headers=other)).status_code == 404
            assert (await client.post(f"/api/v1/recurring/{rule_id}/pause", headers=headers)).json()["data"]["status"] == "paused"
    finally:
        app.dependency_overrides.clear()
    assert await scalars(sessions, select(RecurringRule.status).where(RecurringRule.id == uuid.UUID(rule_id))) == ["paused"]


async def test_database_constraints_hold_even_without_the_application(pg):
    sessions = pg["sessions"]
    world = await seed(sessions, members=1)
    owner, cat = world["users"][0], world["category"].id
    rule_id = await create_rule(sessions, owner, frequency="daily", start_date=D("2024-01-02"),
                                amount_paise=1, category_id=cat, description="constraints")

    async def rejected(*rows: Any) -> bool:
        async with sessions() as s:
            s.add_all(rows)
            try:
                await s.commit()
            except IntegrityError:
                return True
        return False

    def occurrence(**kw: Any) -> RecurringOccurrence:
        return RecurringOccurrence(id=uuid.uuid4(), rule_id=rule_id, occurrence_date=D("2024-01-02"),
                                   status="skipped", skip_reason="TEST", **kw)

    assert not await rejected(occurrence())
    assert await rejected(occurrence())  # UNIQUE (rule_id, occurrence_date)
    assert await rejected(RecurringOccurrence(id=uuid.uuid4(), rule_id=rule_id, occurrence_date=D("2024-01-03"),
                                              status="created", expense_id=uuid.uuid4()))  # deferred FK at COMMIT

    def rule(**kw: Any) -> RecurringRule:
        data = dict(id=uuid.uuid4(), owner_id=owner.id, frequency="daily", start_date=D("2024-01-02"),
                    next_run_date=D("2024-01-02"), status="active", amount_paise=100, category_id=cat,
                    description="x")
        data.update(kw)
        return RecurringRule(**data)

    for bad in (rule(amount_paise=0), rule(frequency="hourly"), rule(status="done"),
                rule(end_date=D("2024-01-01")), rule(split={"split_mode": "equal"})):
        assert await rejected(bad)
