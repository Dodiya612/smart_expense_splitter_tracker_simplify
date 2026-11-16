import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import AuditEvent, Expense, ExpensePayment, ExpenseShare
from app.models.group import (
    Group,
    GroupMember,
    GroupMemberRole,
    GroupMemberStatus,
    GroupType,
)
from app.models.user import User


# ==============================================================================
# In-Memory Test Database & Session Fixtures for Shared Expenses
# ==============================================================================

class FakeExpenseDB:
    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.groups: dict[uuid.UUID, Group] = {}
        self.group_members: dict[tuple[uuid.UUID, uuid.UUID], GroupMember] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.expense_payments: dict[tuple[uuid.UUID, uuid.UUID], ExpensePayment] = {}
        self.expense_shares: dict[tuple[uuid.UUID, uuid.UUID], ExpenseShare] = {}
        self.audit_events: dict[uuid.UUID, AuditEvent] = {}


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items=None, rowcount=1, tuple_res=None):
        self._items = items or []
        self.rowcount = rowcount
        self._tuple_res = tuple_res

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar_one(self):
        return self._items[0] if self._items else 0

    def scalar(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return FakeScalars(self._items)

    def all(self):
        return list(self._items)


class FakeSharedExpenseAsyncSession:
    def __init__(self, db: FakeExpenseDB):
        self.db = db
        self.pending: list[object] = []
        self.fail_on_commit = False

    def add(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(UTC)
        self.pending.append(obj)

    async def flush(self):
        if self.fail_on_commit:
            raise RuntimeError("Simulated database failure during flush/commit")
        # Assign IDs to pending objects without clearing pending
        for obj in self.pending:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        if self.fail_on_commit:
            raise RuntimeError("Simulated database failure during flush/commit")
        for obj in self.pending:
            if isinstance(obj, User):
                self.db.users[obj.id] = obj
            elif isinstance(obj, Group):
                self.db.groups[obj.id] = obj
            elif isinstance(obj, GroupMember):
                self.db.group_members[(obj.group_id, obj.user_id)] = obj
            elif isinstance(obj, Category):
                self.db.categories[obj.id] = obj
            elif isinstance(obj, Expense):
                self.db.expenses[obj.id] = obj
            elif isinstance(obj, ExpensePayment):
                self.db.expense_payments[(obj.expense_id, obj.user_id)] = obj
            elif isinstance(obj, ExpenseShare):
                self.db.expense_shares[(obj.expense_id, obj.user_id)] = obj
            elif isinstance(obj, AuditEvent):
                self.db.audit_events[obj.id] = obj
        self.pending.clear()

        # Wire group relationships
        for grp in self.db.groups.values():
            grp_members = [
                m for m in self.db.group_members.values() if m.group_id == grp.id
            ]
            for m in grp_members:
                m.user = self.db.users.get(m.user_id)
            grp.members = grp_members
            grp.creator = self.db.users.get(grp.created_by)

    async def rollback(self):
        self.pending.clear()

    async def get(self, entity_cls, ident):
        if entity_cls == Category:
            return self.db.categories.get(ident)
        if entity_cls == Group:
            return self.db.groups.get(ident)
        if entity_cls == User:
            return self.db.users.get(ident)
        if entity_cls == Expense:
            return self.db.expenses.get(ident)
        return None

    async def execute(self, stmt):
        sql_str = str(stmt).lower()
        params = stmt.compile().params

        # 1. SELECT User
        if "from users" in sql_str:
            id_val = next(
                (v for k, v in params.items() if (k.startswith("id_") or k == "id") and isinstance(v, uuid.UUID)),
                None,
            )
            matched = list(self.db.users.values())
            if id_val is not None:
                matched = [u for u in matched if u.id == id_val]
            return FakeResult(matched)

        # 2. SELECT Group
        if "from groups" in sql_str:
            id_val = next(
                (v for k, v in params.items() if (k.startswith("id_") or k == "id" or "group_id" in k) and isinstance(v, uuid.UUID)),
                None,
            )
            matched = list(self.db.groups.values())
            if id_val is not None:
                matched = [g for g in matched if g.id == id_val and g.archived_at is None]
            # Ensure relationships are attached
            for g in matched:
                g.members = [m for m in self.db.group_members.values() if m.group_id == g.id]
                for m in g.members:
                    m.user = self.db.users.get(m.user_id)
                g.creator = self.db.users.get(g.created_by)
            return FakeResult(matched)

        # 3. SELECT GroupMember
        if "from group_members" in sql_str:
            gid = next(
                (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            uid = next(
                (v for k, v in params.items() if "user_id" in k and isinstance(v, uuid.UUID) and "group_id" not in k),
                None,
            )
            matched = list(self.db.group_members.values())
            if gid is not None:
                matched = [m for m in matched if m.group_id == gid]
            if uid is not None:
                matched = [m for m in matched if m.user_id == uid]
            return FakeResult(matched)

        # 4. SELECT Expense
        if "from expenses" in sql_str:
            gid = next(
                (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            matched = [e for e in self.db.expenses.values() if e.deleted_at is None]
            if gid is not None:
                matched = [e for e in matched if e.group_id == gid]
            # Attach payments and shares
            for e in matched:
                e.payments = [p for p in self.db.expense_payments.values() if p.expense_id == e.id]
                e.shares = [s for s in self.db.expense_shares.values() if s.expense_id == e.id]
            # Order reverse chronological
            matched.sort(key=lambda e: (e.expense_date, e.created_at), reverse=True)
            return FakeResult(matched)

        return FakeResult([])


@pytest.fixture
def expense_db():
    db = FakeExpenseDB()
    return db


@pytest.fixture
def user_a(expense_db):
    user = User(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        email="user_a@example.com",
        name="User A",
        hashed_password="hashed_pw",
        is_active=True,
    )
    expense_db.users[user.id] = user
    return user


@pytest.fixture
def user_b(expense_db):
    user = User(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        email="user_b@example.com",
        name="User B",
        hashed_password="hashed_pw",
        is_active=True,
    )
    expense_db.users[user.id] = user
    return user


@pytest.fixture
def user_c(expense_db):
    user = User(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        email="user_c@example.com",
        name="User C",
        hashed_password="hashed_pw",
        is_active=True,
    )
    expense_db.users[user.id] = user
    return user


@pytest.fixture
def user_stranger(expense_db):
    user = User(
        id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
        email="stranger@example.com",
        name="Stranger",
        hashed_password="hashed_pw",
        is_active=True,
    )
    expense_db.users[user.id] = user
    return user


@pytest.fixture
def sample_category(expense_db):
    cat = Category(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        name="Food & Dining",
        is_default=True,
    )
    expense_db.categories[cat.id] = cat
    return cat


@pytest.fixture
def sample_group(expense_db, user_a, user_b, user_c):
    now = datetime.now(UTC)
    grp = Group(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="Flatmates Goa Trip",
        type=GroupType.TRIP.value,
        created_by=user_a.id,
        created_at=now,
        updated_at=now,
    )
    expense_db.groups[grp.id] = grp

    # Add user_a as admin
    m_a = GroupMember(
        group_id=grp.id,
        user_id=user_a.id,
        role=GroupMemberRole.ADMIN.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now,
        updated_at=now,
    )
    m_a.user = user_a
    expense_db.group_members[(grp.id, user_a.id)] = m_a

    # Add user_b as member
    m_b = GroupMember(
        group_id=grp.id,
        user_id=user_b.id,
        role=GroupMemberRole.MEMBER.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )
    m_b.user = user_b
    expense_db.group_members[(grp.id, user_b.id)] = m_b

    # Add user_c as member
    m_c = GroupMember(
        group_id=grp.id,
        user_id=user_c.id,
        role=GroupMemberRole.MEMBER.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now + timedelta(seconds=2),
        updated_at=now + timedelta(seconds=2),
    )
    m_c.user = user_c
    expense_db.group_members[(grp.id, user_c.id)] = m_c

    grp.members = [m_a, m_b, m_c]
    grp.creator = user_a
    return grp


@pytest.fixture
def auth_headers_user_a(user_a):
    token = create_access_token(user_a.id, email=user_a.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_user_b(user_b):
    token = create_access_token(user_b.id, email=user_b.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_stranger(user_stranger):
    token = create_access_token(user_stranger.id, email=user_stranger.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_session(expense_db):
    return FakeSharedExpenseAsyncSession(expense_db)


@pytest.fixture
def client(fake_session):
    async def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    yield c
    app.dependency_overrides.clear()


# ==============================================================================
# Tests for US-18: Shared Expense API
# ==============================================================================

@pytest.mark.asyncio
async def test_create_shared_expense_equal_split_default_participants(
    client, sample_group, sample_category, auth_headers_user_a, expense_db
):
    """Test creating an equal split shared expense where participants default to all active members."""
    payload = {
        "amount_paise": 3000,
        "description": "Seafood Dinner",
        "category_id": str(sample_category.id),
        "split_mode": "equal",
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["amountPaise"] == 3000
    assert data["description"] == "Seafood Dinner"
    assert data["splitMode"] == "equal"

    # Default payer is User A
    assert len(data["payments"]) == 1
    assert data["payments"][0]["userId"] == str(sample_group.created_by)
    assert data["payments"][0]["amountPaise"] == 3000

    # 3 active members get 1000 each
    assert len(data["shares"]) == 3
    total_shares = sum(s["amountPaise"] for s in data["shares"])
    assert total_shares == 3000
    for s in data["shares"]:
        assert s["amountPaise"] == 1000

    # Verify audit event was logged in DB
    assert len(expense_db.audit_events) == 1
    audit = list(expense_db.audit_events.values())[0]
    assert audit.action == "expense_created"
    assert audit.entity_type == "expense"


@pytest.mark.asyncio
async def test_create_shared_expense_equal_split_deterministic_remainder(
    client, sample_group, sample_category, auth_headers_user_a
):
    """Test largest-remainder deterministic tie-breaking for equal split with odd paise."""
    # 1000 paise / 3 members = 333 + 333 + 334
    payload = {
        "amount_paise": 1000,
        "description": "Beach Shack Snacks",
        "category_id": str(sample_category.id),
        "split_mode": "equal",
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 201
    data = response.json()
    shares = data["shares"]
    assert len(shares) == 3
    assert sum(s["amountPaise"] for s in shares) == 1000
    # First member (joined earliest) gets the extra paisa
    assert shares[0]["amountPaise"] == 334
    assert shares[1]["amountPaise"] == 333
    assert shares[2]["amountPaise"] == 333


@pytest.mark.asyncio
async def test_create_shared_expense_exact_split_success(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a
):
    """Test exact split where participants are explicitly specified with integer paise amounts."""
    payload = {
        "amount_paise": 5000,
        "description": "Taxi Ride",
        "category_id": str(sample_category.id),
        "split_mode": "exact",
        "participant_user_ids": [str(user_a.id), str(user_b.id)],
        "split_weights": {
            str(user_a.id): 2000,
            str(user_b.id): 3000,
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["amountPaise"] == 5000
    assert len(data["shares"]) == 2
    share_map = {s["userId"]: s["amountPaise"] for s in data["shares"]}
    assert share_map[str(user_a.id)] == 2000
    assert share_map[str(user_b.id)] == 3000


@pytest.mark.asyncio
async def test_create_shared_expense_exact_split_unbalanced_rejected(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a
):
    """Test rejection when exact split weights do not sum to total amount."""
    payload = {
        "amount_paise": 5000,
        "description": "Taxi Ride",
        "category_id": str(sample_category.id),
        "split_mode": "exact",
        "participant_user_ids": [str(user_a.id), str(user_b.id)],
        "split_weights": {
            str(user_a.id): 2000,
            str(user_b.id): 2999,  # Sums to 4999 != 5000
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 400
    data = response.json()
    assert data["code"] in ("INVALID_SPLIT", "UNBALANCED_SHARES")


@pytest.mark.asyncio
async def test_create_shared_expense_percentage_split_success(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a
):
    """Test percentage split summing strictly to 100%."""
    payload = {
        "amount_paise": 10000,
        "description": "Villa Booking Advance",
        "category_id": str(sample_category.id),
        "split_mode": "percentage",
        "participant_user_ids": [str(user_a.id), str(user_b.id)],
        "split_weights": {
            str(user_a.id): 40.0,
            str(user_b.id): 60.0,
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 201
    data = response.json()
    share_map = {s["userId"]: s["amountPaise"] for s in data["shares"]}
    assert share_map[str(user_a.id)] == 4000
    assert share_map[str(user_b.id)] == 6000


@pytest.mark.asyncio
async def test_create_shared_expense_percentage_split_not_100_rejected(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a
):
    """Test rejection when percentages do not sum to 100%."""
    payload = {
        "amount_paise": 10000,
        "description": "Villa Booking",
        "category_id": str(sample_category.id),
        "split_mode": "percentage",
        "participant_user_ids": [str(user_a.id), str(user_b.id)],
        "split_weights": {
            str(user_a.id): 40.0,
            str(user_b.id): 50.0,  # 90% != 100%
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_SPLIT"


@pytest.mark.asyncio
async def test_create_shared_expense_parts_split_success(
    client, sample_group, sample_category, user_a, user_b, user_c, auth_headers_user_a
):
    """Test parts/ratio-based split mode."""
    # 6000 paise with ratios 1:2:3 -> 1000, 2000, 3000
    payload = {
        "amount_paise": 6000,
        "description": "Groceries",
        "category_id": str(sample_category.id),
        "split_mode": "parts",
        "participant_user_ids": [str(user_a.id), str(user_b.id), str(user_c.id)],
        "split_weights": {
            str(user_a.id): 1,
            str(user_b.id): 2,
            str(user_c.id): 3,
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 201
    data = response.json()
    share_map = {s["userId"]: s["amountPaise"] for s in data["shares"]}
    assert share_map[str(user_a.id)] == 1000
    assert share_map[str(user_b.id)] == 2000
    assert share_map[str(user_c.id)] == 3000


@pytest.mark.asyncio
async def test_create_shared_expense_multiple_payers_mixed_contributions(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a
):
    """Test expense creation with multiple payers (mixed contributions)."""
    payload = {
        "amount_paise": 5000,
        "description": "Group Grocery Shopping",
        "category_id": str(sample_category.id),
        "split_mode": "equal",
        "payments": {
            str(user_a.id): 2000,
            str(user_b.id): 3000,
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data["payments"]) == 2
    payment_map = {p["userId"]: p["amountPaise"] for p in data["payments"]}
    assert payment_map[str(user_a.id)] == 2000
    assert payment_map[str(user_b.id)] == 3000


@pytest.mark.asyncio
async def test_create_shared_expense_multiple_payers_unbalanced_rejected(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a
):
    """Test rejection when payments do not sum to total amount."""
    payload = {
        "amount_paise": 5000,
        "description": "Grocery",
        "category_id": str(sample_category.id),
        "split_mode": "equal",
        "payments": {
            str(user_a.id): 2000,
            str(user_b.id): 2500,  # 4500 != 5000
        },
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "UNBALANCED_PAYMENTS"


@pytest.mark.asyncio
async def test_create_shared_expense_payer_not_member_rejected(
    client, sample_group, sample_category, user_stranger, auth_headers_user_a
):
    """Test rejection when an external non-member is specified as payer."""
    payload = {
        "amount_paise": 3000,
        "description": "Drinks",
        "category_id": str(sample_category.id),
        "paid_by_user_id": str(user_stranger.id),
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "PAYER_NOT_MEMBER"


@pytest.mark.asyncio
async def test_create_shared_expense_participant_not_member_rejected(
    client, sample_group, sample_category, user_a, user_stranger, auth_headers_user_a
):
    """Test rejection when an external non-member is specified as participant."""
    payload = {
        "amount_paise": 3000,
        "description": "Drinks",
        "category_id": str(sample_category.id),
        "participant_user_ids": [str(user_a.id), str(user_stranger.id)],
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "PARTICIPANT_NOT_MEMBER"


@pytest.mark.asyncio
async def test_create_shared_expense_stranger_caller_rejected(
    client, sample_group, sample_category, auth_headers_stranger
):
    """Test that a non-member caller is blocked with 403 Forbidden."""
    payload = {
        "amount_paise": 3000,
        "description": "Party Snacks",
        "category_id": str(sample_category.id),
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_stranger,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "GROUP_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_create_shared_expense_negative_or_zero_amount_rejected(
    client, sample_group, sample_category, auth_headers_user_a
):
    """Test that negative or zero expense amount is rejected."""
    payload = {
        "amount_paise": 0,
        "description": "Zero Expense",
        "category_id": str(sample_category.id),
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_shared_expense_category_not_found(
    client, sample_group, auth_headers_user_a
):
    """Test rejection when category UUID does not exist."""
    payload = {
        "amount_paise": 2000,
        "description": "Unknown Category Expense",
        "category_id": str(uuid.uuid4()),
    }
    response = await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json=payload,
        headers=auth_headers_user_a,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CATEGORY_NOT_FOUND"


@pytest.mark.asyncio
async def test_atomic_transaction_rollback_on_database_failure(
    client, sample_group, sample_category, auth_headers_user_a, fake_session, expense_db
):
    """Test that an unexpected DB failure during creation rolls back all tables completely."""
    fake_session.fail_on_commit = True
    payload = {
        "amount_paise": 3000,
        "description": "Rollback Test Expense",
        "category_id": str(sample_category.id),
    }
    with pytest.raises(RuntimeError, match="Simulated database failure"):
        await client.post(
            f"/api/v1/groups/{sample_group.id}/expenses",
            json=payload,
            headers=auth_headers_user_a,
        )

    # Verify no partial rows persisted in DB
    assert len(expense_db.expenses) == 0
    assert len(expense_db.expense_payments) == 0
    assert len(expense_db.expense_shares) == 0
    assert len(expense_db.audit_events) == 0


@pytest.mark.asyncio
async def test_list_shared_expenses(
    client, sample_group, sample_category, auth_headers_user_a
):
    """Test listing shared expenses for a group in reverse chronological order."""
    # Create two expenses
    await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json={
            "amount_paise": 1500,
            "description": "Lunch Day 1",
            "category_id": str(sample_category.id),
        },
        headers=auth_headers_user_a,
    )
    await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json={
            "amount_paise": 2500,
            "description": "Dinner Day 1",
            "category_id": str(sample_category.id),
        },
        headers=auth_headers_user_a,
    )

    response = await client.get(
        f"/api/v1/groups/{sample_group.id}/expenses",
        headers=auth_headers_user_a,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["description"] == "Dinner Day 1"
    assert data[1]["description"] == "Lunch Day 1"


@pytest.mark.asyncio
async def test_group_balances_ledger_integration(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b
):
    """Test ledger integration dynamically deriving zero-sum net positions and transfers."""
    # Expense 1: User A pays 3000 for A, B, C (1000 each)
    await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json={
            "amount_paise": 3000,
            "description": "Fuel & Tolls",
            "category_id": str(sample_category.id),
            "split_mode": "equal",
        },
        headers=auth_headers_user_a,
    )

    # Expense 2: User B pays 1500 for B and C (750 each)
    await client.post(
        f"/api/v1/groups/{sample_group.id}/expenses",
        json={
            "amount_paise": 1500,
            "description": "Desserts",
            "category_id": str(sample_category.id),
            "split_mode": "equal",
            "participant_user_ids": [str(user_b.id), str(user_c.id)],
        },
        headers=auth_headers_user_b,
    )

    # Fetch balances
    response = await client.get(
        f"/api/v1/groups/{sample_group.id}/balances",
        headers=auth_headers_user_a,
    )
    assert response.status_code == 200
    data = response.json()
    net = data["net_positions"]

    # Expected net positions:
    # User A: paid 3000, share 1000 -> +2000 paise
    # User B: paid 1500, share (1000 + 750 = 1750) -> -250 paise
    # User C: paid 0, share (1000 + 750 = 1750) -> -1750 paise
    assert net[str(user_a.id)] == 2000
    assert net[str(user_b.id)] == -250
    assert net[str(user_c.id)] == -1750
    # Zero-sum invariant
    assert sum(net.values()) == 0

    # Suggested transfers
    transfers = data["suggested_transfers"]
    assert len(transfers) >= 1
    # Check that debtors pay creditors accurately
    total_transferred = sum(t["amount_paise"] for t in transfers)
    assert total_transferred == 2000

