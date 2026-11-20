"""Real-PostgreSQL check of the analytics SQL (US-12 / T-42).

Runs the PRODUCT.md section 05 demo through the real services and the real
aggregate SQL (UNION ALL legs, SUM over BIGINT paise, date_trunc, Monday weeks)
on a throwaway local database, created and dropped by the ``pg`` fixture from
tests/test_transaction_integrity_pg.py (local hosts only, never Supabase).

The whole module is SKIPPED when no local PostgreSQL is reachable; set
COINSCIOUS_TEST_PG_URL to an admin URL on a local server to run it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.category import Category
from app.models.expense import Expense
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus, GroupType
from app.models.user import User
from app.schemas.settlement import SettlementCreateRequest
from app.schemas.shared_expense import SharedExpenseCreateRequest
from app.services import analytics_service, settlement_service, shared_expense_service
from tests import test_transaction_integrity_pg as pg_support

pg = pg_support.pg  # throwaway database fixture (skips cleanly without PostgreSQL)

GROCERIES = uuid.uuid4()
TRAVEL = uuid.uuid4()
FOOD = uuid.uuid4()
MONDAY = date(2026, 11, 16)
START = date(2026, 11, 1)
END = date(2026, 11, 30)


async def seed_demo(sessions: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    now = datetime.now(UTC)
    users = [
        User(id=uuid.uuid4(), email=f"{n}@example.com", name=n.title(), hashed_password="x", is_active=True)
        for n in ("alex", "blair", "casey")
    ]
    cats = [
        Category(id=GROCERIES, name="Groceries", is_default=True),
        Category(id=TRAVEL, name="Travel & Transport", is_default=True),
        Category(id=FOOD, name="Food & Dining", is_default=True),
    ]
    grp = Group(id=uuid.uuid4(), name="Flat Expenses", type=GroupType.FLAT.value,
                created_by=users[0].id, created_at=now, updated_at=now)
    async with sessions() as s:
        s.add_all([*users, *cats, grp])
        await s.flush()
        for i, u in enumerate(users):  # fixed order: Alex first, so he gets the extra paisa
            s.add(GroupMember(
                group_id=grp.id, user_id=u.id,
                role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
                status=GroupMemberStatus.ACTIVE.value, joined_at=now + timedelta(seconds=i), updated_at=now,
            ))
        await s.commit()
    return {"alex": users[0], "blair": users[1], "casey": users[2], "group": grp}


async def figures(sessions: async_sessionmaker[AsyncSession], user: User) -> tuple[int, int, int, int]:
    async with sessions() as s:
        r = await analytics_service.get_summary(s, user, START, END)
    return r.share_paise, r.cash_paid_paise, r.owed_to_you_paise, r.you_owe_paise


async def test_demo_dataset_on_real_postgres(pg):
    sessions = pg["sessions"]
    w = await seed_demo(sessions)
    alex, blair, casey, group = w["alex"], w["blair"], w["casey"], w["group"]

    async with sessions() as s:  # 1. Alex pays ₹3,000 groceries, split by three
        await shared_expense_service.create_shared_expense(
            s, group.id, alex,
            SharedExpenseCreateRequest(amount_paise=300000, description="Groceries",
                                       category_id=GROCERIES, expense_date=MONDAY),
        )
    assert await figures(sessions, alex) == (100000, 300000, 200000, 0)

    async with sessions() as s:  # 2. Blair repays Alex ₹1,000
        await settlement_service.create_settlement(
            s, group.id, blair, SettlementCreateRequest(payer_id=blair.id, payee_id=alex.id, amount_paise=100000)
        )
    assert await figures(sessions, alex) == (100000, 300000, 100000, 0)
    assert await figures(sessions, blair) == (100000, 0, 0, 0)

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
    assert await figures(sessions, alex) == (150000, 350000, 100000, 0)

    async with sessions() as s:  # 4. Casey pays ₹100 chai, split by three
        await shared_expense_service.create_shared_expense(
            s, group.id, casey,
            SharedExpenseCreateRequest(amount_paise=10000, description="Chai",
                                       category_id=FOOD, expense_date=MONDAY + timedelta(days=2)),
        )
    assert await figures(sessions, alex) == (153334, 350000, 96666, 0)
    assert await figures(sessions, blair) == (103333, 0, 0, 3333)
    assert await figures(sessions, casey) == (103333, 10000, 0, 93333)

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
