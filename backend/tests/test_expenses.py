import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import Expense
from app.models.idempotency import IdempotencyRecord
from app.models.user import User


class FakeExpenseDB:
    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.idempotency_records: dict[tuple[uuid.UUID, str], IdempotencyRecord] = {}


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

    def one(self):
        if self._tuple_res is not None:
            return self._tuple_res
        return self._items[0] if self._items else (0, 0)


class FakeAsyncSession:
    def __init__(self, db: FakeExpenseDB):
        self.db = db
        self.pending: list[object] = []

    def add(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        self.pending.append(obj)

    async def commit(self):
        for obj in self.pending:
            if isinstance(obj, User):
                self.db.users[obj.id] = obj
            elif isinstance(obj, Category):
                self.db.categories[obj.id] = obj
            elif isinstance(obj, Expense):
                self.db.expenses[obj.id] = obj
            elif isinstance(obj, IdempotencyRecord):
                k = (obj.user_id, obj.key)
                if k in self.db.idempotency_records and self.db.idempotency_records[k].id != obj.id:
                    raise IntegrityError("unique constraint uq_idempotency_records_user_key", params={}, orig=Exception())
                self.db.idempotency_records[k] = obj
        self.pending.clear()

    async def rollback(self):
        self.pending.clear()

    async def refresh(self, obj):
        pass

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, stmt):
        # Auto flush pending
        await self.commit()

        sql_str = str(stmt).lower()
        params = stmt.compile().params

        # 1. SELECT User
        if "from users" in sql_str:
            id_val = next((v for k, v in params.items() if "id" in k), None)
            if id_val is not None:
                matched = [u for u in self.db.users.values() if u.id == id_val]
                return FakeResult(matched)
            return FakeResult(list(self.db.users.values()))

        # 2. SELECT Category
        if "from categories" in sql_str:
            cat_id = next((v for k, v in params.items() if "id_1" in k or "id" in k), None)
            user_id = next((v for k, v in params.items() if "owner_id" in k or "user" in k), None)
            matched = []
            for c in self.db.categories.values():
                if cat_id is not None and c.id != cat_id:
                    continue
                if c.is_default or (user_id is not None and c.owner_id == user_id):
                    matched.append(c)
            return FakeResult(matched)

        # 3. SELECT / INSERT IdempotencyRecord
        if "from idempotency_records" in sql_str:
            user_id = next((v for k, v in params.items() if "user_id" in k), None)
            key_val = next((v for k, v in params.items() if "key" in k), None)
            matched = []
            for (uid, k), rec in self.db.idempotency_records.items():
                if (user_id is None or uid == user_id) and (key_val is None or k == key_val):
                    matched.append(rec)
            return FakeResult(matched)

        # 4. UPDATE Expense
        if sql_str.startswith("update expenses"):
            exp_id = params.get("id_1") or params.get("id")
            user_id = params.get("user_id_1") or params.get("user_id")
            exp_version = params.get("version_1") if "version_1" in params else params.get("version")

            target = None
            for e in self.db.expenses.values():
                if exp_id and e.id != exp_id:
                    continue
                if user_id and e.user_id != user_id:
                    continue
                if exp_version is not None and e.version != exp_version:
                    continue
                if e.deleted_at is not None:
                    continue
                target = e
                break

            if not target:
                return FakeResult(rowcount=0)

            # Apply updates
            for col, val in params.items():
                if col in ("amount_minor", "description", "category_id", "expense_date", "notes", "merchant", "payment_mode", "receipt_id", "version", "updated_at"):
                    setattr(target, col, val)
            return FakeResult(rowcount=1)

        # 5. Count / Sum aggregate query
        if "count(expenses.id)" in sql_str or "coalesce(sum(expenses.amount_minor)" in sql_str:
            user_id = params.get("user_id_1") or params.get("user_id")
            from_d = params.get("expense_date_1") or params.get("expense_date")
            to_d = params.get("expense_date_2")
            search_pattern = params.get("description_1") or params.get("merchant_1")

            matched = [
                e for e in self.db.expenses.values()
                if e.user_id == user_id and e.deleted_at is None
            ]
            if from_d:
                matched = [e for e in matched if e.expense_date >= from_d]
            if to_d:
                matched = [e for e in matched if e.expense_date <= to_d]
            if search_pattern:
                query_str = search_pattern.strip("%").lower()
                matched = [
                    e for e in matched
                    if query_str in (e.description or "").lower() or query_str in (e.merchant or "").lower()
                ]

            total_paise = sum(e.amount_minor for e in matched)
            count = len(matched)
            if "coalesce(sum" in sql_str:
                return FakeResult(tuple_res=(total_paise, count))
            return FakeResult([count])

        # 6. SELECT Expense
        if "from expenses" in sql_str:
            exp_id = params.get("id_1") or (params.get("id") if "expenses.id" in sql_str else None)
            user_id = params.get("user_id_1") or params.get("user_id")
            cat_id = params.get("category_id_1") or params.get("category_id")
            from_d = params.get("expense_date_1") or params.get("expense_date")
            to_d = params.get("expense_date_2")
            search_pattern = params.get("description_1") or params.get("merchant_1")

            matched = list(self.db.expenses.values())
            if exp_id is not None:
                matched = [e for e in matched if e.id == exp_id]
            if user_id is not None:
                matched = [e for e in matched if e.user_id == user_id]
            if "deleted_at is null" in sql_str:
                matched = [e for e in matched if e.deleted_at is None]
            if cat_id is not None:
                matched = [e for e in matched if e.category_id == cat_id]
            if from_d is not None:
                matched = [e for e in matched if e.expense_date >= from_d]
            if to_d is not None:
                matched = [e for e in matched if e.expense_date <= to_d]
            if search_pattern:
                query_str = search_pattern.strip("%").lower()
                matched = [
                    e for e in matched
                    if query_str in (e.description or "").lower() or query_str in (e.merchant or "").lower()
                ]

            # Sort descending by date, then created_at
            matched.sort(key=lambda x: (x.expense_date, x.created_at), reverse=True)

            # Pagination if present
            limit_val = params.get("param_1")
            offset_val = params.get("param_2")
            if offset_val is not None:
                matched = matched[offset_val:]
            if limit_val is not None:
                matched = matched[:limit_val]

            return FakeResult(matched)

        return FakeResult([])


@pytest.fixture
def fake_db():
    db = FakeExpenseDB()
    # Default category: Food & Dining
    cat = Category(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        name="Food & Dining",
        is_default=True,
        owner_id=None,
        created_at=datetime.now(UTC),
    )
    db.categories[cat.id] = cat
    return db


@pytest.fixture
def test_user(fake_db):
    user = User(
        id=uuid.uuid4(),
        email="testuser@example.com",
        name="Test User",
        hashed_password="hashed_pw",
        is_active=True,
    )
    fake_db.users[user.id] = user
    return user


@pytest.fixture
def other_user(fake_db):
    user = User(
        id=uuid.uuid4(),
        email="otheruser@example.com",
        name="Other User",
        hashed_password="hashed_pw",
        is_active=True,
    )
    fake_db.users[user.id] = user
    return user


@pytest.fixture
def auth_headers(test_user):
    token = create_access_token(user_id=test_user.id, email=test_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_auth_headers(other_user):
    token = create_access_token(user_id=other_user.id, email=other_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def async_client(fake_db):
    async def override_get_db():
        session = FakeAsyncSession(fake_db)
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_create_expense_success(async_client, auth_headers):
    payload = {
        "amount_minor": 25000,
        "description": "Lunch with colleagues",
        "category_id": "00000000-0000-4000-8000-000000000001",
        "occurred_on": "2026-10-25",
        "merchant": "Bawarchi",
        "payment_mode": "upi",
    }
    resp = await async_client.post("/api/v1/expenses", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["amountMinor"] == 25000
    assert data["amountPaise"] == 25000
    assert data["description"] == "Lunch with colleagues"
    assert data["version"] == 1
    assert data["merchant"] == "Bawarchi"
    assert data["paymentMode"] == "upi"
    assert data["deletedAt"] is None


@pytest.mark.anyio
async def test_create_expense_validation_errors(async_client, auth_headers):
    # 1. Zero amount
    resp = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 0,
            "description": "Zero test",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "VALIDATION_ERROR"

    # 2. Negative amount
    resp = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": -1500,
            "description": "Negative test",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # 3. Floating point amount
    resp = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 250.75,
            "description": "Float test",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # 4. Future date beyond tomorrow
    future_date = (datetime.now(UTC).date() + timedelta(days=5)).isoformat()
    resp = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 5000,
            "description": "Future test",
            "category_id": "00000000-0000-4000-8000-000000000001",
            "expense_date": future_date,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422

    # 5. Non-existent category
    resp = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 5000,
            "description": "Category test",
            "category_id": str(uuid.uuid4()),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_CATEGORY"


@pytest.mark.anyio
async def test_idempotency_workflow(async_client, auth_headers, other_auth_headers):
    key = "unique-key-12345"
    payload = {
        "amount_minor": 18000,
        "description": "Uber ride",
        "category_id": "00000000-0000-4000-8000-000000000001",
    }
    headers = {**auth_headers, "Idempotency-Key": key}

    # 1. Initial creation
    resp1 = await async_client.post("/api/v1/expenses", json=payload, headers=headers)
    assert resp1.status_code == 201
    exp_id = resp1.json()["data"]["id"]

    # 2. Immediate identical retry returns identical resource with idempotent replay header
    resp2 = await async_client.post("/api/v1/expenses", json=payload, headers=headers)
    assert resp2.status_code == 201
    assert resp2.json()["data"]["id"] == exp_id
    assert resp2.headers.get("X-Idempotent-Replay") == "true"

    # 3. Reuse same key with DIFFERENT payload yields 409 Conflict
    diff_payload = {
        "amount_minor": 99000,
        "description": "Different expensive ride",
        "category_id": "00000000-0000-4000-8000-000000000001",
    }
    resp3 = await async_client.post("/api/v1/expenses", json=diff_payload, headers=headers)
    assert resp3.status_code == 409
    assert resp3.json()["code"] == "IDEMPOTENCY_CONFLICT"

    # 4. Another user with the same idempotency key succeeds (separate user namespace)
    other_headers = {**other_auth_headers, "Idempotency-Key": key}
    resp4 = await async_client.post("/api/v1/expenses", json=payload, headers=other_headers)
    assert resp4.status_code == 201
    assert resp4.json()["data"]["id"] != exp_id


@pytest.mark.anyio
async def test_get_and_list_expenses(async_client, auth_headers, other_auth_headers):
    # Create two expenses for test_user
    payload1 = {
        "amount_minor": 12000,
        "description": "Groceries A",
        "category_id": "00000000-0000-4000-8000-000000000001",
    }
    payload2 = {
        "amount_minor": 8000,
        "description": "Groceries B",
        "category_id": "00000000-0000-4000-8000-000000000001",
    }
    r1 = await async_client.post("/api/v1/expenses", json=payload1, headers=auth_headers)
    await async_client.post("/api/v1/expenses", json=payload2, headers=auth_headers)
    id1 = r1.json()["data"]["id"]

    # 1. Retrieve single expense
    get_res = await async_client.get(f"/api/v1/expenses/{id1}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["data"]["id"] == id1

    # 2. Other user accessing this expense receives 404
    other_res = await async_client.get(f"/api/v1/expenses/{id1}", headers=other_auth_headers)
    assert other_res.status_code == 404

    # 3. List expenses
    list_res = await async_client.get("/api/v1/expenses", headers=auth_headers)
    assert list_res.status_code == 200
    items = list_res.json()["data"]
    assert len(items) == 2
    assert list_res.json()["meta"]["total"] == 2

    # 4. Other user list is empty
    other_list = await async_client.get("/api/v1/expenses", headers=other_auth_headers)
    assert other_list.status_code == 200
    assert len(other_list.json()["data"]) == 0


@pytest.mark.anyio
async def test_update_expense_and_version_checks(async_client, auth_headers, other_auth_headers):
    create_res = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 10000,
            "description": "Team snacks",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers,
    )
    exp_id = create_res.json()["data"]["id"]
    assert create_res.json()["data"]["version"] == 1

    # 1. Successful update increments version to 2
    update_res = await async_client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={
            "version": 1,
            "description": "Team dinner & snacks",
            "amount_minor": 15000,
        },
        headers=auth_headers,
    )
    assert update_res.status_code == 200
    assert update_res.json()["data"]["version"] == 2
    assert update_res.json()["data"]["description"] == "Team dinner & snacks"
    assert update_res.json()["data"]["amountMinor"] == 15000

    # 2. Update with stale version 1 returns 409 Conflict
    stale_res = await async_client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={
            "version": 1,
            "description": "Overwrite attempt with stale version",
        },
        headers=auth_headers,
    )
    assert stale_res.status_code == 409
    assert stale_res.json()["code"] == "VERSION_CONFLICT"

    # 3. Update using If-Match header with matching version 2 succeeds
    header_res = await async_client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Header update"},
        headers={**auth_headers, "If-Match": "2"},
    )
    assert header_res.status_code == 200
    assert header_res.json()["data"]["version"] == 3

    # 4. Another user cannot update (returns 404)
    forbidden_update = await async_client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"version": 3, "description": "Hacker edit"},
        headers=other_auth_headers,
    )
    assert forbidden_update.status_code == 404


@pytest.mark.anyio
async def test_soft_delete_and_restore(async_client, auth_headers, other_auth_headers):
    create_res = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 50000,
            "description": "Flight ticket",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers,
    )
    exp_id = create_res.json()["data"]["id"]

    # Verify spending totals before delete
    totals_before = await async_client.get("/api/v1/expenses/totals", headers=auth_headers)
    assert totals_before.status_code == 200
    assert totals_before.json()["data"]["totalPaise"] == 50000
    assert totals_before.json()["data"]["count"] == 1

    # 1. Other user cannot delete
    other_del = await async_client.delete(f"/api/v1/expenses/{exp_id}", headers=other_auth_headers)
    assert other_del.status_code == 404

    # 2. Soft delete expense
    del_res = await async_client.delete(f"/api/v1/expenses/{exp_id}", headers=auth_headers)
    assert del_res.status_code == 200
    assert del_res.json()["data"]["deleted"] is True

    # 3. Deleted expense vanishes from ordinary GET results
    get_res = await async_client.get(f"/api/v1/expenses/{exp_id}", headers=auth_headers)
    assert get_res.status_code == 404

    list_res = await async_client.get("/api/v1/expenses", headers=auth_headers)
    assert len(list_res.json()["data"]) == 0

    # 4. Deleted expense is excluded from totals
    totals_after = await async_client.get("/api/v1/expenses/totals", headers=auth_headers)
    assert totals_after.json()["data"]["totalPaise"] == 0
    assert totals_after.json()["data"]["count"] == 0

    # 5. Another user cannot restore
    other_restore = await async_client.post(f"/api/v1/expenses/{exp_id}/restore", headers=other_auth_headers)
    assert other_restore.status_code == 404

    # 6. Restore expense
    restore_res = await async_client.post(f"/api/v1/expenses/{exp_id}/restore", headers=auth_headers)
    assert restore_res.status_code == 200
    assert restore_res.json()["data"]["id"] == exp_id
    assert restore_res.json()["data"]["deletedAt"] is None

    # 7. Restored expense is visible in GET and totals again
    get_restored = await async_client.get(f"/api/v1/expenses/{exp_id}", headers=auth_headers)
    assert get_restored.status_code == 200

    totals_restored = await async_client.get("/api/v1/expenses/totals", headers=auth_headers)
    assert totals_restored.json()["data"]["totalPaise"] == 50000

    # 8. Restoring an active expense returns 400
    dup_restore = await async_client.post(f"/api/v1/expenses/{exp_id}/restore", headers=auth_headers)
    assert dup_restore.status_code == 400
    assert dup_restore.json()["code"] == "EXPENSE_NOT_DELETED"


@pytest.mark.anyio
async def test_unauthenticated_requests(async_client):
    # Unauthenticated GET
    r1 = await async_client.get("/api/v1/expenses")
    assert r1.status_code == 401
    assert r1.json()["code"] == "UNAUTHORIZED"

    # Unauthenticated POST
    r2 = await async_client.post("/api/v1/expenses", json={"amount_minor": 1000, "description": "Coffee"})
    assert r2.status_code == 401


@pytest.mark.anyio
async def test_custom_category_authorization(async_client, fake_db, test_user, other_user, auth_headers, other_auth_headers):
    # 1. Create a custom category owned by test_user
    cat_user1 = Category(
        id=uuid.uuid4(),
        name="User 1 Special Category",
        is_default=False,
        owner_id=test_user.id,
        created_at=datetime.now(UTC),
    )
    fake_db.categories[cat_user1.id] = cat_user1

    # 2. test_user can create expense using their own custom category
    res1 = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 1000,
            "description": "User 1 item",
            "category_id": str(cat_user1.id),
        },
        headers=auth_headers,
    )
    assert res1.status_code == 201

    # 3. other_user attempting to use test_user's custom category is rejected with 400
    res2 = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 1000,
            "description": "Stolen category item",
            "category_id": str(cat_user1.id),
        },
        headers=other_auth_headers,
    )
    assert res2.status_code == 400
    assert res2.json()["code"] == "INVALID_CATEGORY"


@pytest.mark.anyio
async def test_filter_and_search_expenses(async_client, auth_headers):
    # Category 1: Food
    cat_id = "00000000-0000-4000-8000-000000000001"
    # Create 3 expenses
    await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 5000,
            "description": "Pizza Hut Dinner",
            "merchant": "Pizza Hut",
            "category_id": cat_id,
            "expense_date": "2026-10-15",
        },
        headers=auth_headers,
    )
    await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 3000,
            "description": "Starbucks Coffee",
            "merchant": "Starbucks",
            "category_id": cat_id,
            "expense_date": "2026-10-20",
        },
        headers=auth_headers,
    )
    await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 12000,
            "description": "Dominos Party",
            "merchant": "Dominos",
            "category_id": cat_id,
            "expense_date": "2026-10-28",
        },
        headers=auth_headers,
    )

    # 1. Search by text "Starbucks"
    res_search = await async_client.get("/api/v1/expenses?q=Starbucks", headers=auth_headers)
    assert res_search.status_code == 200
    assert len(res_search.json()["data"]) == 1
    assert res_search.json()["data"][0]["merchant"] == "Starbucks"

    # 2. Filter by date range (from 2026-10-18 to 2026-10-25)
    res_date = await async_client.get("/api/v1/expenses?from=2026-10-18&to=2026-10-25", headers=auth_headers)
    assert res_date.status_code == 200
    assert len(res_date.json()["data"]) == 1
    assert res_date.json()["data"][0]["description"] == "Starbucks Coffee"

    # 3. Pagination limit
    res_paged = await async_client.get("/api/v1/expenses?limit=2&offset=0", headers=auth_headers)
    assert res_paged.status_code == 200
    assert len(res_paged.json()["data"]) == 2
    assert res_paged.json()["meta"]["total"] == 3
    assert res_paged.json()["meta"]["nextCursor"] == "2"


@pytest.mark.anyio
async def test_update_missing_version_rejected(async_client, auth_headers):
    create_res = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 1000,
            "description": "No version update test",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=auth_headers,
    )
    exp_id = create_res.json()["data"]["id"]

    # Attempt update without version in body and without If-Match header
    upd_res = await async_client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Missing version"},
        headers=auth_headers,
    )
    assert upd_res.status_code == 409
    assert upd_res.json()["code"] == "VERSION_REQUIRED"


@pytest.mark.anyio
async def test_receipt_id_support(async_client, auth_headers):
    rec_id = uuid.uuid4()
    create_res = await async_client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 4500,
            "description": "Expense with receipt",
            "category_id": "00000000-0000-4000-8000-000000000001",
            "receipt_id": str(rec_id),
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201
    assert create_res.json()["data"]["receiptId"] == str(rec_id)
