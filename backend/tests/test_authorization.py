import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.authorization import (
    Action,
    CategoryPolicy,
    ExpensePolicy,
    GroupPolicy,
    SessionPolicy,
    validate_protected_fields_update,
)
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import Expense
from app.models.idempotency import IdempotencyRecord
from app.models.refresh_token import RefreshToken
from app.models.user import User


class FakeAuthTestDB:
    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.idempotency_records: dict[tuple[uuid.UUID, str], IdempotencyRecord] = {}
        self.tokens: dict[uuid.UUID, RefreshToken] = {}


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


class FakeAuthAsyncSession:
    def __init__(self, db: FakeAuthTestDB):
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
            elif isinstance(obj, RefreshToken):
                self.db.tokens[obj.id] = obj
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

    async def execute(self, stmt):
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

            for col, val in params.items():
                if col in ("amount_minor", "description", "category_id", "expense_date", "notes", "merchant", "payment_mode", "receipt_id", "version", "updated_at"):
                    setattr(target, col, val)
            return FakeResult(rowcount=1)

        # 5. Count / Sum aggregate query
        if "count(expenses.id)" in sql_str or "coalesce(sum(expenses.amount_minor)" in sql_str:
            user_id = params.get("user_id_1") or params.get("user_id")
            matched = [
                e for e in self.db.expenses.values()
                if e.user_id == user_id and e.deleted_at is None
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
            matched = list(self.db.expenses.values())
            if exp_id is not None:
                matched = [e for e in matched if e.id == exp_id]
            if user_id is not None:
                matched = [e for e in matched if e.user_id == user_id]
            if "deleted_at is null" in sql_str:
                matched = [e for e in matched if e.deleted_at is None]
            matched.sort(key=lambda x: (x.expense_date, x.created_at), reverse=True)
            return FakeResult(matched)

        # 7. SELECT RefreshToken
        if "from refresh_tokens" in sql_str:
            fam_or_id = next((v for k, v in params.items() if "family" in k or "id" in k), None)
            user_id = next((v for k, v in params.items() if "user" in k), None)
            matched = list(self.db.tokens.values())
            if fam_or_id is not None:
                matched = [t for t in matched if t.family_id == fam_or_id or t.id == fam_or_id]
            if user_id is not None:
                matched = [t for t in matched if t.user_id == user_id]
            return FakeResult(matched)

        # 8. UPDATE RefreshToken
        if "update refresh_tokens" in sql_str:
            fam_val = next((v for k, v in params.items() if "family" in k), None)
            if fam_val is not None:
                for t in self.db.tokens.values():
                    if t.family_id == fam_val:
                        t.is_revoked = True
            return FakeResult([])

        return FakeResult([])


@pytest.fixture
def auth_db():
    db = FakeAuthTestDB()
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
def user_a(auth_db):
    user = User(
        id=uuid.uuid4(),
        email="user_a@example.com",
        name="User A",
        hashed_password="hashed_pw_a",
        is_active=True,
    )
    auth_db.users[user.id] = user
    return user


@pytest.fixture
def user_b(auth_db):
    user = User(
        id=uuid.uuid4(),
        email="user_b@example.com",
        name="User B",
        hashed_password="hashed_pw_b",
        is_active=True,
    )
    auth_db.users[user.id] = user
    return user


@pytest.fixture
def token_a(user_a):
    return create_access_token(user_id=user_a.id, email=user_a.email)


@pytest.fixture
def token_b(user_b):
    return create_access_token(user_id=user_b.id, email=user_b.email)


@pytest.fixture
def headers_a(token_a):
    return {"Authorization": f"Bearer {token_a}"}


@pytest.fixture
def headers_b(token_b):
    return {"Authorization": f"Bearer {token_b}"}


@pytest.fixture
async def client_auth(auth_db):
    async def override_get_db():
        session = FakeAuthAsyncSession(auth_db)
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


# ==============================================================================
# Security Tests
# ==============================================================================

@pytest.mark.anyio
async def test_unauthenticated_requests_rejected(client_auth):
    """
    Acceptance Criterion 1: Current-user Authentication
    Ensure unauthenticated requests are strictly rejected with HTTP 401 UNAUTHORIZED
    across all protected endpoints.
    """
    random_uuid = uuid.uuid4()
    endpoints = [
        ("GET", "/api/v1/expenses"),
        ("POST", "/api/v1/expenses"),
        ("GET", "/api/v1/expenses/totals"),
        ("GET", f"/api/v1/expenses/{random_uuid}"),
        ("PATCH", f"/api/v1/expenses/{random_uuid}"),
        ("DELETE", f"/api/v1/expenses/{random_uuid}"),
        ("POST", f"/api/v1/expenses/{random_uuid}/restore"),
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/auth/sessions"),
        ("DELETE", f"/api/v1/auth/sessions/{random_uuid}"),
    ]

    for method, path in endpoints:
        resp = await client_auth.request(method, path)
        assert resp.status_code == 401, f"{method} {path} did not reject unauthenticated access"
        data = resp.json()
        assert data["code"] in ("UNAUTHORIZED", "INVALID_TOKEN")
        assert data["isRetryable"] is False
        assert "Authentication required" in data["message"] or "User not found" in data["message"]


@pytest.mark.anyio
async def test_authenticated_user_accesses_own_records(client_auth, headers_a):
    """
    Acceptance Criterion 1 & 2:
    An authenticated user can perform all allowed CRUD operations on their own expense.
    """
    # 1. Create expense
    res_create = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 15000,
            "description": "Team lunch",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    assert res_create.status_code == 201
    exp_id = res_create.json()["data"]["id"]

    # 2. Read expense
    res_get = await client_auth.get(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert res_get.status_code == 200
    assert res_get.json()["data"]["description"] == "Team lunch"

    # 3. Update expense
    res_update = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Team lunch updated", "version": 1},
        headers=headers_a,
    )
    assert res_update.status_code == 200
    assert res_update.json()["data"]["version"] == 2

    # 4. Delete expense
    res_del = await client_auth.delete(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert res_del.status_code == 200

    # 5. Restore expense
    res_restore = await client_auth.post(f"/api/v1/expenses/{exp_id}/restore", headers=headers_a)
    assert res_restore.status_code == 200
    assert res_restore.json()["data"]["deletedAt"] is None


@pytest.mark.anyio
async def test_cross_user_isolation_cannot_read_other_user_expense(client_auth, headers_a, headers_b):
    """
    Acceptance Criterion 2: Record-Level Authorization & IDOR Protection
    User A cannot read User B's private expense record.
    Returns HTTP 404 NOT_FOUND to prevent ID enumeration.
    """
    res_create_b = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 99000,
            "description": "User B Private Purchase",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_b,
    )
    assert res_create_b.status_code == 201
    exp_b_id = res_create_b.json()["data"]["id"]

    # User A tries to view User B's expense
    res_get_a = await client_auth.get(f"/api/v1/expenses/{exp_b_id}", headers=headers_a)
    assert res_get_a.status_code == 404
    data = res_get_a.json()
    assert data["code"] == "NOT_FOUND"
    assert "Private Purchase" not in res_get_a.text


@pytest.mark.anyio
async def test_cross_user_isolation_cannot_update_or_delete_other_user_expense(
    client_auth, headers_a, headers_b, auth_db
):
    """
    Acceptance Criterion 2 & 6:
    User A cannot update or delete User B's record.
    Database record remains unaltered.
    """
    res_create_b = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 45000,
            "description": "User B Secret Expense",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_b,
    )
    exp_b_id = res_create_b.json()["data"]["id"]
    exp_b_uuid = uuid.UUID(exp_b_id)

    # User A attempts unauthorized update
    res_patch = await client_auth.patch(
        f"/api/v1/expenses/{exp_b_id}",
        json={"description": "Hacked by User A", "version": 1},
        headers=headers_a,
    )
    assert res_patch.status_code == 404
    assert auth_db.expenses[exp_b_uuid].description == "User B Secret Expense"

    # User A attempts unauthorized delete
    res_delete = await client_auth.delete(f"/api/v1/expenses/{exp_b_id}", headers=headers_a)
    assert res_delete.status_code == 404
    assert auth_db.expenses[exp_b_uuid].deleted_at is None


@pytest.mark.anyio
async def test_listing_and_totals_never_leak_foreign_expenses(client_auth, headers_a, headers_b):
    """
    Acceptance Criterion 2 & 6: Database and Handler Safety
    User A's listing and aggregate spending totals never include User B's expenses.
    """
    # User A creates 2 expenses: 10,000 and 20,000 paise
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 10000, "description": "Expense A1", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 20000, "description": "Expense A2", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )

    # User B creates 1 expense: 50,000 paise
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 50000, "description": "Expense B1", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_b,
    )

    # Check User A's totals
    totals_a = await client_auth.get("/api/v1/expenses/totals", headers=headers_a)
    assert totals_a.status_code == 200
    assert totals_a.json()["data"]["totalPaise"] == 30000
    assert totals_a.json()["data"]["count"] == 2

    # Check User B's totals
    totals_b = await client_auth.get("/api/v1/expenses/totals", headers=headers_b)
    assert totals_b.status_code == 200
    assert totals_b.json()["data"]["totalPaise"] == 50000
    assert totals_b.json()["data"]["count"] == 1


@pytest.mark.anyio
async def test_reject_protected_field_ownership_tampering(client_auth, headers_a, user_a, user_b, auth_db):
    """
    Acceptance Criterion 5: Protected-Field Updates
    Users cannot modify ownership / creator IDs (user_id, userId, owner_id) via PATCH request body.
    Returns HTTP 400 with code PROTECTED_FIELD_MODIFICATION and leaves DB unchanged.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 12000, "description": "My lunch", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)

    # 1. Attempt snake_case user_id modification
    tamper_res1 = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"user_id": str(user_b.id), "version": 1},
        headers=headers_a,
    )
    assert tamper_res1.status_code == 400
    assert tamper_res1.json()["code"] == "PROTECTED_FIELD_MODIFICATION"
    assert "user_id" in tamper_res1.json()["message"]
    assert auth_db.expenses[exp_uuid].user_id == user_a.id

    # 2. Attempt camelCase userId modification
    tamper_res2 = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"userId": str(user_b.id), "version": 1},
        headers=headers_a,
    )
    assert tamper_res2.status_code == 400
    assert tamper_res2.json()["code"] == "PROTECTED_FIELD_MODIFICATION"
    assert auth_db.expenses[exp_uuid].user_id == user_a.id

    # 3. Attempt owner_id modification
    tamper_res3 = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"owner_id": str(user_b.id), "version": 1},
        headers=headers_a,
    )
    assert tamper_res3.status_code == 400
    assert tamper_res3.json()["code"] == "PROTECTED_FIELD_MODIFICATION"
    assert auth_db.expenses[exp_uuid].user_id == user_a.id


@pytest.mark.anyio
async def test_reject_privilege_escalation_and_role_manipulation(client_auth, headers_a):
    """
    Acceptance Criterion 5:
    A user cannot grant themselves administrator privileges or alter protected role fields.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 8000, "description": "Coffee", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]

    for privileged_payload in [
        {"role": "admin", "version": 1},
        {"roles": ["admin", "superadmin"], "version": 1},
        {"is_admin": True, "version": 1},
        {"isAdmin": True, "version": 1},
        {"is_superuser": True, "version": 1},
        {"group_role": "admin", "version": 1},
        {"permissions": ["all"], "version": 1},
    ]:
        tamper_res = await client_auth.patch(
            f"/api/v1/expenses/{exp_id}",
            json=privileged_payload,
            headers=headers_a,
        )
        assert tamper_res.status_code == 400
        assert tamper_res.json()["code"] == "PROTECTED_FIELD_MODIFICATION"


@pytest.mark.anyio
async def test_reject_primary_key_and_audit_timestamp_tampering(client_auth, headers_a, auth_db):
    """
    Acceptance Criterion 5:
    A user cannot alter id, created_at, or deleted_at via update payloads.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 14000, "description": "Snacks", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)
    original_created_at = auth_db.expenses[exp_uuid].created_at

    for audit_payload in [
        {"id": str(uuid.uuid4()), "version": 1},
        {"created_at": "2020-01-01T00:00:00Z", "version": 1},
        {"createdAt": "2020-01-01T00:00:00Z", "version": 1},
        {"deleted_at": "2020-01-01T00:00:00Z", "version": 1},
    ]:
        tamper_res = await client_auth.patch(
            f"/api/v1/expenses/{exp_id}",
            json=audit_payload,
            headers=headers_a,
        )
        assert tamper_res.status_code == 400
        assert tamper_res.json()["code"] == "PROTECTED_FIELD_MODIFICATION"

    assert auth_db.expenses[exp_uuid].created_at == original_created_at


@pytest.mark.anyio
async def test_reject_foreign_user_id_in_creation_payload(client_auth, headers_a, user_b):
    """
    Acceptance Criterion 5:
    Supplying another user's ID in request body during creation cannot forge ownership.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={
            "user_id": str(user_b.id),
            "amount_minor": 30000,
            "description": "Spoofed User B expense",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "PROTECTED_FIELD_MODIFICATION"


@pytest.mark.anyio
async def test_query_parameter_user_id_tampering_rejected(client_auth, headers_a, user_b):
    """
    Acceptance Criterion 5 & 6:
    Supplying another user's ID in query parameters does not bypass authorization.
    """
    res_list = await client_auth.get(f"/api/v1/expenses?user_id={user_b.id}", headers=headers_a)
    assert res_list.status_code == 403
    assert res_list.json()["code"] == "FORBIDDEN"

    res_totals = await client_auth.get(f"/api/v1/expenses/totals?user_id={user_b.id}", headers=headers_a)
    assert res_totals.status_code == 403
    assert res_totals.json()["code"] == "FORBIDDEN"


@pytest.mark.anyio
async def test_category_authorization_policy(client_auth, headers_a, headers_b, user_a, user_b, auth_db):
    """
    Acceptance Criterion 2 & 3:
    Shared category policy:
    - User can use default category.
    - User can use own custom category.
    - User cannot use foreign custom category.
    - Default category cannot be updated or deleted.
    """
    # 1. User B creates custom category
    custom_b = Category(
        id=uuid.uuid4(),
        owner_id=user_b.id,
        name="User B Private Project",
        is_default=False,
        created_at=datetime.now(UTC),
    )
    auth_db.categories[custom_b.id] = custom_b

    # 2. User A attempts to create expense referencing User B's category
    res = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 10000,
            "description": "Unauthorized category usage",
            "category_id": str(custom_b.id),
        },
        headers=headers_a,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CATEGORY"

    # 3. Direct CategoryPolicy checks
    default_cat = auth_db.categories[uuid.UUID("00000000-0000-4000-8000-000000000001")]
    # Reading default category is permitted for all users
    CategoryPolicy.authorize(user_a, default_cat, Action.READ)

    # Attempting to modify or delete default category raises 403
    with pytest.raises(Exception) as exc_update:
        CategoryPolicy.authorize(user_a, default_cat, Action.UPDATE)
    assert exc_update.value.status_code == 403


@pytest.mark.anyio
async def test_session_authorization_policy_and_isolation(client_auth, headers_a, headers_b, user_a, user_b, auth_db):
    """
    Acceptance Criterion 2 & 3:
    Session authorization: User A cannot view or revoke User B's session.
    """
    session_b = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_b.id,
        family_id=uuid.uuid4(),
        token_hash="hash_b",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        is_revoked=False,
    )
    auth_db.tokens[session_b.id] = session_b

    # User A attempts to revoke User B's session
    res_revoke = await client_auth.delete(f"/api/v1/auth/sessions/{session_b.family_id}", headers=headers_a)
    assert res_revoke.status_code == 404
    assert res_revoke.json()["code"] == "SESSION_NOT_FOUND"
    assert auth_db.tokens[session_b.id].is_revoked is False

    # Direct policy check: raises 404
    with pytest.raises(Exception) as exc_info:
        SessionPolicy.authorize(user_a, session_b, Action.DELETE)
    assert exc_info.value.status_code == 404


def test_group_authorization_policy(user_a, user_b):
    """
    Acceptance Criterion 2 & 3:
    Shared Group authorization policy:
    - Non-member cannot access private group resources.
    - Member can access group resources.
    - Member without admin role cannot perform admin actions.
    - Admin can perform admin actions.
    """
    group_id = uuid.uuid4()
    members = {user_a.id}
    admins = {user_a.id}

    # 1. Member access succeeds
    GroupPolicy.authorize_member(user_a, group_id, members)

    # 2. Non-member access raises 403 GROUP_ACCESS_DENIED
    with pytest.raises(Exception) as exc_non_member:
        GroupPolicy.authorize_member(user_b, group_id, members)
    assert exc_non_member.value.status_code == 403
    assert exc_non_member.value.detail["code"] == "GROUP_ACCESS_DENIED"

    # 3. Member who is not admin cannot perform admin action
    members_with_b = {user_a.id, user_b.id}
    with pytest.raises(Exception) as exc_non_admin:
        GroupPolicy.authorize_admin(user_b, group_id, members_with_b, admins)
    assert exc_non_admin.value.status_code == 403
    assert exc_non_admin.value.detail["code"] == "INSUFFICIENT_PERMISSIONS"

    # 4. Admin succeeds
    GroupPolicy.authorize_admin(user_a, group_id, members_with_b, admins)


def test_validate_protected_fields_utility():
    """
    Acceptance Criterion 5:
    Direct verification of validate_protected_fields_update helper.
    """
    # Safe payload with only allowed fields
    validate_protected_fields_update(
        {"description": "Valid update", "amount_minor": 1000},
        allowed_fields={"description", "amount_minor"},
    )

    # Disallowed field
    with pytest.raises(Exception) as exc_disallowed:
        validate_protected_fields_update(
            {"description": "Valid", "extra_bad_field": "val"},
            allowed_fields={"description"},
        )
    assert exc_disallowed.value.status_code == 400
    assert exc_disallowed.value.detail["code"] == "DISALLOWED_FIELD_UPDATE"

    # Protected field
    with pytest.raises(Exception) as exc_protected:
        validate_protected_fields_update(
            {"user_id": str(uuid.uuid4())},
        )
    assert exc_protected.value.status_code == 400
    assert exc_protected.value.detail["code"] == "PROTECTED_FIELD_MODIFICATION"
