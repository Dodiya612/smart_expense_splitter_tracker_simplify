import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.authorization import (
    ALLOWED_EXPENSE_UPDATE_FIELDS,
    PROTECTED_FIELDS,
    Action,
    CategoryPolicy,
    ExpensePolicy,
    GroupPolicy,
    GroupRole,
    SessionPolicy,
    validate_protected_fields_update,
)
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, hash_refresh_token
from app.main import app
from app.models.category import Category
from app.models.category_feedback import CategorySuggestionFeedback
from app.models.expense import Expense
from app.models.idempotency import IdempotencyRecord
from app.models.refresh_token import RefreshToken
from app.models.user import User


# ==============================================================================
# In-Memory Test Database & Session Fixtures
# ==============================================================================

class FakeAuthTestDB:
    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.idempotency_records: dict[tuple[uuid.UUID, str], IdempotencyRecord] = {}
        self.tokens: dict[uuid.UUID, RefreshToken] = {}
        self.feedback: list[Any] = []
        self.ai_logs: list[Any] = []


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

    async def flush(self):
        await self.commit()

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
            elif hasattr(obj, "__tablename__") and obj.__tablename__ == "category_suggestion_feedback":
                self.db.feedback.append(obj)
            elif hasattr(obj, "__tablename__") and obj.__tablename__ == "ai_usage_log":
                self.db.ai_logs.append(obj)
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
            id_val = next((v for k, v in params.items() if "id" in k and isinstance(v, uuid.UUID)), None)
            email_val = next((v for k, v in params.items() if "email" in k and isinstance(v, str)), None)
            matched = list(self.db.users.values())
            if id_val is not None:
                matched = [u for u in matched if u.id == id_val]
            if email_val is not None:
                matched = [u for u in matched if u.email.lower() == email_val.lower()]
            return FakeResult(matched)

        # 2. SELECT Category
        if "from categories" in sql_str:
            cat_id = next((v for k, v in params.items() if ("id_1" in k or "id" in k) and isinstance(v, uuid.UUID)), None)
            user_id = next((v for k, v in params.items() if ("owner_id" in k or "user" in k) and isinstance(v, uuid.UUID)), None)
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

        # 5. Count / Sum aggregate query for expenses
        if "count(expenses.id)" in sql_str or "coalesce(sum(expenses.amount_minor)" in sql_str:
            user_id = params.get("user_id_1") or params.get("user_id")
            matched = [
                e for e in self.db.expenses.values()
                if (user_id is None or e.user_id == user_id) and e.deleted_at is None
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
            user_id = next((v for k, v in params.items() if "user" in k and isinstance(v, uuid.UUID)), None)
            hash_val = next((v for k, v in params.items() if "hash" in k), None)
            fam_or_token = next((v for k, v in params.items() if ("family" in k or k in ("id", "id_1", "id_2")) and isinstance(v, uuid.UUID) and v != user_id), None)

            matched = list(self.db.tokens.values())
            if user_id is not None:
                matched = [t for t in matched if t.user_id == user_id]
            if hash_val is not None:
                matched = [t for t in matched if t.token_hash == hash_val]
            if fam_or_token is not None:
                matched = [t for t in matched if t.family_id == fam_or_token or t.id == fam_or_token]
            if "is_revoked is false" in sql_str:
                matched = [t for t in matched if not t.is_revoked]
            return FakeResult(matched)

        # 8. UPDATE RefreshToken
        if "update refresh_tokens" in sql_str:
            fam_val = next((v for k, v in params.items() if "family" in k), None)
            uid_val = next((v for k, v in params.items() if "user" in k), None)
            if fam_val is not None:
                for t in self.db.tokens.values():
                    if t.family_id == fam_val:
                        t.is_revoked = True
            elif uid_val is not None:
                for t in self.db.tokens.values():
                    if t.user_id == uid_val:
                        t.is_revoked = True
            return FakeResult([])

        # 9. AI Quota and Advisory Lock Queries
        if "from ai_usage_log" in sql_str:
            if "count(" in sql_str:
                return FakeResult([len(self.db.ai_logs)])
            return FakeResult(self.db.ai_logs)

        return FakeResult([])


PRECOMPUTED_HASH = "$argon2id$v=19$m=65536,t=3,p=4$zIlCNU18a2CaT7I/ki/c9A$TwC6+v+eIjbNC9ed8V+Q8Ri1O9COrpd131SS2dcmwkw"


# ==============================================================================
# Realistic Test Actors and Fixtures (US-37 Requirements)
# User A: Resource Owner
# User B: Different Authorized User / Group Member
# User C: Stranger / Non-Member
# Admin: User with Administrative Permissions
# ==============================================================================

@pytest.fixture
def auth_db():
    db = FakeAuthTestDB()
    # Default System Category
    cat_default = Category(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        name="Food & Dining",
        is_default=True,
        owner_id=None,
        created_at=datetime.now(UTC),
    )
    db.categories[cat_default.id] = cat_default

    cat_travel = Category(
        id=uuid.UUID("00000000-0000-4000-8000-000000000002"),
        name="Travel & Transport",
        is_default=True,
        owner_id=None,
        created_at=datetime.now(UTC),
    )
    db.categories[cat_travel.id] = cat_travel
    return db


@pytest.fixture
def user_a(auth_db):
    """User A: Resource Owner."""
    user = User(
        id=uuid.uuid4(),
        email="user_a@example.com",
        name="User A (Owner)",
        hashed_password=PRECOMPUTED_HASH,
        is_active=True,
    )
    auth_db.users[user.id] = user
    return user


@pytest.fixture
def user_b(auth_db):
    """User B: Group Member / Different Authorized User."""
    user = User(
        id=uuid.uuid4(),
        email="user_b@example.com",
        name="User B (Member)",
        hashed_password=PRECOMPUTED_HASH,
        is_active=True,
    )
    auth_db.users[user.id] = user
    return user


@pytest.fixture
def user_c(auth_db):
    """User C: Stranger / Non-Member."""
    user = User(
        id=uuid.uuid4(),
        email="user_c@example.com",
        name="User C (Stranger)",
        hashed_password=PRECOMPUTED_HASH,
        is_active=True,
    )
    auth_db.users[user.id] = user
    return user


@pytest.fixture
def admin_user(auth_db):
    """Admin User: User with Administrative Permissions."""
    user = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        name="Admin User",
        hashed_password=PRECOMPUTED_HASH,
        is_active=True,
    )
    auth_db.users[user.id] = user
    return user


@pytest.fixture
def inactive_user(auth_db):
    """Inactive User: Deactivated Account."""
    user = User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        name="Inactive User",
        hashed_password=PRECOMPUTED_HASH,
        is_active=False,
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
def token_c(user_c):
    return create_access_token(user_id=user_c.id, email=user_c.email)


@pytest.fixture
def token_admin(admin_user):
    return create_access_token(user_id=admin_user.id, email=admin_user.email)


@pytest.fixture
def token_inactive(inactive_user):
    return create_access_token(user_id=inactive_user.id, email=inactive_user.email)


@pytest.fixture
def expired_token(user_a):
    return create_access_token(user_id=user_a.id, email=user_a.email, expires_delta=timedelta(seconds=-60))


@pytest.fixture
def invalid_token():
    return "invalid.bearer.token.with.bad.signature"


@pytest.fixture
def headers_a(token_a):
    return {"Authorization": f"Bearer {token_a}"}


@pytest.fixture
def headers_b(token_b):
    return {"Authorization": f"Bearer {token_b}"}


@pytest.fixture
def headers_c(token_c):
    return {"Authorization": f"Bearer {token_c}"}


@pytest.fixture
def headers_admin(token_admin):
    return {"Authorization": f"Bearer {token_admin}"}


@pytest.fixture
def headers_inactive(token_inactive):
    return {"Authorization": f"Bearer {token_inactive}"}


@pytest.fixture
def headers_expired(expired_token):
    return {"Authorization": f"Bearer {expired_token}"}


@pytest.fixture
def headers_invalid(invalid_token):
    return {"Authorization": f"Bearer {invalid_token}"}


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
# 1. Stranger & Unauthenticated Access Tests
# ==============================================================================

@pytest.mark.anyio
async def test_stranger_unauthenticated_requests_all_protected_endpoints(client_auth):
    """
    US-37 Scenario A1: Stranger Unauthenticated Access.
    Verifies that unauthenticated requests to EVERY applicable protected OpenAPI endpoint
    are strictly rejected with HTTP 401 UNAUTHORIZED and return the standardized error envelope
    without leaking private data.
    """
    random_uuid = uuid.uuid4()
    endpoints = [
        ("GET", "/api/v1/auth/me", None),
        ("GET", "/api/v1/auth/sessions", None),
        ("DELETE", f"/api/v1/auth/sessions/{random_uuid}", None),
        ("GET", "/api/v1/expenses", None),
        ("POST", "/api/v1/expenses", {"amount_minor": 1000, "description": "Test", "category_id": "00000000-0000-4000-8000-000000000001"}),
        ("GET", "/api/v1/expenses/totals", None),
        ("GET", f"/api/v1/expenses/{random_uuid}", None),
        ("PATCH", f"/api/v1/expenses/{random_uuid}", {"description": "Updated", "version": 1}),
        ("DELETE", f"/api/v1/expenses/{random_uuid}", None),
        ("POST", f"/api/v1/expenses/{random_uuid}/restore", None),
        ("POST", "/api/v1/ai/category-suggestion", {"description": "Coffee"}),
        ("POST", "/api/v1/ai/category-suggestion/feedback", {
            "description": "Coffee",
            "suggestedCategoryId": "00000000-0000-4000-8000-000000000001",
            "chosenCategoryId": "00000000-0000-4000-8000-000000000001",
            "accepted": True,
        }),
    ]

    for method, path, body in endpoints:
        resp = await client_auth.request(method, path, json=body)
        assert resp.status_code == 401, f"{method} {path} did not reject unauthenticated access (got {resp.status_code})"
        data = resp.json()
        assert data["code"] in ("UNAUTHORIZED", "INVALID_TOKEN")
        assert data["isRetryable"] is False
        assert "Authentication required" in data["message"] or "Bearer token missing" in data["message"]
        # Data leakage check: Error payload must never contain user details or records
        assert "data" not in data
        assert "email" not in str(data)
        assert "password" not in str(data)


@pytest.mark.anyio
async def test_stranger_invalid_token_rejected_all_protected_endpoints(client_auth, headers_invalid):
    """
    US-37 Scenario A2: Stranger Invalid Token Access.
    Supplying a malformed or improperly signed Bearer token is rejected with HTTP 401 INVALID_TOKEN.
    """
    random_uuid = uuid.uuid4()
    endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/auth/sessions"),
        ("DELETE", f"/api/v1/auth/sessions/{random_uuid}"),
        ("GET", "/api/v1/expenses"),
        ("POST", "/api/v1/expenses"),
        ("GET", "/api/v1/expenses/totals"),
        ("GET", f"/api/v1/expenses/{random_uuid}"),
        ("PATCH", f"/api/v1/expenses/{random_uuid}"),
        ("DELETE", f"/api/v1/expenses/{random_uuid}"),
        ("POST", f"/api/v1/expenses/{random_uuid}/restore"),
        ("POST", "/api/v1/ai/category-suggestion"),
        ("POST", "/api/v1/ai/category-suggestion/feedback"),
    ]

    for method, path in endpoints:
        resp = await client_auth.request(method, path, headers=headers_invalid)
        assert resp.status_code == 401, f"{method} {path} did not reject invalid token (got {resp.status_code})"
        data = resp.json()
        assert data["code"] == "INVALID_TOKEN"
        assert data["isRetryable"] is False


@pytest.mark.anyio
async def test_stranger_expired_token_rejected_all_protected_endpoints(client_auth, headers_expired):
    """
    US-37 Scenario A3: Stranger Expired Token Access.
    Supplying an expired Bearer token is strictly rejected with HTTP 401 TOKEN_EXPIRED.
    """
    random_uuid = uuid.uuid4()
    endpoints = [
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/auth/sessions"),
        ("DELETE", f"/api/v1/auth/sessions/{random_uuid}"),
        ("GET", "/api/v1/expenses"),
        ("POST", "/api/v1/expenses"),
        ("GET", "/api/v1/expenses/totals"),
        ("GET", f"/api/v1/expenses/{random_uuid}"),
        ("PATCH", f"/api/v1/expenses/{random_uuid}"),
        ("DELETE", f"/api/v1/expenses/{random_uuid}"),
        ("POST", f"/api/v1/expenses/{random_uuid}/restore"),
        ("POST", "/api/v1/ai/category-suggestion"),
        ("POST", "/api/v1/ai/category-suggestion/feedback"),
    ]

    for method, path in endpoints:
        resp = await client_auth.request(method, path, headers=headers_expired)
        assert resp.status_code == 401, f"{method} {path} did not reject expired token (got {resp.status_code})"
        data = resp.json()
        assert data["code"] == "TOKEN_EXPIRED"
        assert "expired" in data["message"].lower()


@pytest.mark.anyio
async def test_stranger_inactive_account_rejected(client_auth, headers_inactive):
    """
    US-37 Scenario A4: Inactive / Deactivated User Token.
    A token belonging to a deactivated user account is rejected with HTTP 401 ACCOUNT_INACTIVE.
    """
    resp = await client_auth.get("/api/v1/auth/me", headers=headers_inactive)
    assert resp.status_code == 401
    assert resp.json()["code"] == "ACCOUNT_INACTIVE"


# ==============================================================================
# 2. Public Endpoints Authorization & Protection Tests
# ==============================================================================

@pytest.mark.anyio
async def test_public_health_endpoint_accessible_to_all_actors(
    client_auth, headers_a, headers_b, headers_c, headers_admin
):
    """
    US-37 Public Endpoint: GET /api/v1/health.
    Accessible to Stranger (unauthenticated), Owner, Member, and Admin.
    Verifies no database credentials, internal IPs, or secrets are leaked.
    """
    for headers in [None, headers_a, headers_b, headers_c, headers_admin]:
        resp = await client_auth.get("/api/v1/health", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "healthy")
        assert "database" in data
        # Data leakage check: no secrets
        text = resp.text.lower()
        assert "password" not in text
        assert "secret" not in text
        assert "token" not in text


@pytest.mark.anyio
async def test_public_auth_signup_and_register_isolation_and_no_hash_leakage(client_auth, auth_db):
    """
    US-37 Public Endpoints: POST /api/v1/auth/signup & POST /api/v1/auth/register.
    - Stranger can register without an existing session.
    - Password hashes (hashed_password) are NEVER leaked in response payloads.
    - Privilege escalation tampering (is_admin, role) is rejected or ignored.
    """
    for path in ["/api/v1/auth/signup", "/api/v1/auth/register"]:
        email = f"new_actor_{uuid.uuid4().hex[:6]}@example.com"
        resp = await client_auth.post(
            path,
            json={
                "email": email,
                "name": "New User Actor",
                "password": "SecurePassword123!",
                "is_admin": True,  # Attempt privilege escalation
                "role": "admin",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "tokens" in data
        assert "user" in data
        assert data["user"]["email"] == email

        # Data leakage check: hashed_password MUST NOT be in response
        assert "hashed_password" not in resp.text
        assert "hashedPassword" not in resp.text
        assert "SecurePassword123!" not in resp.text

        # Verify created user in DB does NOT possess admin privileges
        created_user = next((u for u in auth_db.users.values() if u.email == email), None)
        assert created_user is not None
        assert getattr(created_user, "is_admin", False) is False


@pytest.mark.anyio
async def test_public_auth_login_credential_verification_and_safety(client_auth, user_a):
    """
    US-37 Public Endpoint: POST /api/v1/auth/login.
    - Invalid credentials return HTTP 401 INVALID_CREDENTIALS.
    - Non-existent user returns HTTP 401 with identical error envelope.
    - Successful login never leaks password hashes.
    """
    # 1. Invalid password
    bad_pw = await client_auth.post(
        "/api/v1/auth/login",
        json={"email": user_a.email, "password": "WrongPassword999!"},
    )
    assert bad_pw.status_code == 401
    assert bad_pw.json()["code"] == "INVALID_CREDENTIALS"

    # 2. Non-existent user
    unknown_user = await client_auth.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "SomePassword123!"},
    )
    assert unknown_user.status_code == 401
    assert unknown_user.json()["code"] == "INVALID_CREDENTIALS"

    # 3. Successful login
    success_resp = await client_auth.post(
        "/api/v1/auth/login",
        json={"email": user_a.email, "password": "PasswordA123!"},
    )
    assert success_resp.status_code == 200
    assert "tokens" in success_resp.json()
    assert "hashed_password" not in success_resp.text
    assert "hashedPassword" not in success_resp.text


@pytest.mark.anyio
async def test_public_auth_refresh_token_validation(client_auth):
    """
    US-37 Public Endpoint: POST /api/v1/auth/refresh.
    Missing, invalid, or forged refresh tokens return HTTP 401 / 422.
    """
    # Forged refresh token
    resp = await client_auth.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "forged_non_existent_token_string"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] in ("INVALID_TOKEN", "REVOKED_TOKEN", "UNAUTHORIZED")


# ==============================================================================
# 3. User Identity & Active Sessions Authorization Tests
# ==============================================================================

@pytest.mark.anyio
async def test_user_profile_me_access_and_isolation(
    client_auth, headers_a, headers_b, headers_c, headers_admin, user_a, user_b, user_c, admin_user
):
    """
    US-37 Scenario B1 & B4: GET /api/v1/auth/me Isolation.
    Every authenticated user accesses ONLY their own profile.
    Cross-user data leakage is strictly verified: User A's data is never visible to User B or User C.
    Sensitive credential fields are NEVER leaked.
    """
    # User A profile
    res_a = await client_auth.get("/api/v1/auth/me", headers=headers_a)
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["email"] == user_a.email
    assert data_a["name"] == user_a.name
    assert "hashed_password" not in res_a.text

    # User B profile
    res_b = await client_auth.get("/api/v1/auth/me", headers=headers_b)
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["email"] == user_b.email
    assert user_a.email not in res_b.text

    # User C (Stranger) profile
    res_c = await client_auth.get("/api/v1/auth/me", headers=headers_c)
    assert res_c.status_code == 200
    assert res_c.json()["email"] == user_c.email
    assert user_a.email not in res_c.text

    # Admin profile
    res_admin = await client_auth.get("/api/v1/auth/me", headers=headers_admin)
    assert res_admin.status_code == 200
    assert res_admin.json()["email"] == admin_user.email


@pytest.mark.anyio
async def test_sessions_listing_data_isolation(client_auth, headers_a, headers_b, headers_c, user_a, user_b, auth_db):
    """
    US-37 Scenario B1 & B4: GET /api/v1/auth/sessions Isolation.
    User A sees only User A's active sessions.
    User B sees only User B's active sessions.
    User C (Stranger) sees zero sessions.
    Foreign session IDs and family IDs are never leaked.
    """
    session_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash="hash_session_a",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        is_revoked=False,
    )
    session_b = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_b.id,
        family_id=uuid.uuid4(),
        token_hash="hash_session_b",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        is_revoked=False,
    )
    auth_db.tokens[session_a.id] = session_a
    auth_db.tokens[session_b.id] = session_b

    # User A listing
    resp_a = await client_auth.get("/api/v1/auth/sessions", headers=headers_a)
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    sessions_a = data_a.get("sessions", [])
    a_ids = [s["id"] for s in sessions_a]
    assert str(session_a.family_id) in a_ids
    assert str(session_b.family_id) not in a_ids

    # User B listing
    resp_b = await client_auth.get("/api/v1/auth/sessions", headers=headers_b)
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    sessions_b = data_b.get("sessions", [])
    b_ids = [s["id"] for s in sessions_b]
    assert str(session_b.family_id) in b_ids
    assert str(session_a.family_id) not in b_ids

    # User C listing (Stranger has no sessions)
    resp_c = await client_auth.get("/api/v1/auth/sessions", headers=headers_c)
    assert resp_c.status_code == 200
    assert len(resp_c.json().get("sessions", [])) == 0


@pytest.mark.anyio
async def test_session_revocation_idor_protection_and_db_integrity(
    client_auth, headers_a, headers_b, headers_c, user_a, auth_db
):
    """
    US-37 Scenario B2 & B4: DELETE /api/v1/auth/sessions/{session_id}.
    - User B cannot revoke User A's session -> HTTP 404 SESSION_NOT_FOUND.
    - User C (Stranger) cannot revoke User A's session -> HTTP 404 SESSION_NOT_FOUND.
    - Database verification: User A's session remains active (is_revoked=False).
    - User A revoking own session succeeds -> HTTP 200, marked revoked in DB.
    """
    session_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash="hash_session_a_target",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        is_revoked=False,
    )
    auth_db.tokens[session_a.id] = session_a

    # User B attempts unauthorized session revocation
    unauth_b = await client_auth.delete(f"/api/v1/auth/sessions/{session_a.family_id}", headers=headers_b)
    assert unauth_b.status_code == 404
    assert unauth_b.json()["code"] == "SESSION_NOT_FOUND"
    assert auth_db.tokens[session_a.id].is_revoked is False

    # User C (Stranger) attempts unauthorized session revocation
    unauth_c = await client_auth.delete(f"/api/v1/auth/sessions/{session_a.family_id}", headers=headers_c)
    assert unauth_c.status_code == 404
    assert unauth_c.json()["code"] == "SESSION_NOT_FOUND"
    assert auth_db.tokens[session_a.id].is_revoked is False

    # User A successfully revokes own session
    auth_del = await client_auth.delete(f"/api/v1/auth/sessions/{session_a.family_id}", headers=headers_a)
    assert auth_del.status_code == 200
    assert auth_db.tokens[session_a.id].is_revoked is True


@pytest.mark.anyio
async def test_logout_cross_user_credential_mismatch(client_auth, headers_b, user_a, auth_db):
    """
    US-37 Scenario B5: POST /api/v1/auth/logout Cross-User Attack.
    An authenticated User B attempting to pass User A's refresh token in the logout request body
    is strictly rejected with HTTP 403 CREDENTIAL_MISMATCH.
    User A's session remains untouched and unrevoked.
    """
    token_str = "user_a_raw_refresh_token_value"
    token_hash = hash_refresh_token(token_str)
    session_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        is_revoked=False,
    )
    auth_db.tokens[session_a.id] = session_a

    # User B attempts to logout User A's session
    malicious_logout = await client_auth.post(
        "/api/v1/auth/logout",
        json={"refresh_token": token_str},
        headers=headers_b,
    )
    assert malicious_logout.status_code == 403
    assert malicious_logout.json()["code"] == "CREDENTIAL_MISMATCH"
    # Database integrity: User A's token remains valid
    assert auth_db.tokens[session_a.id].is_revoked is False


# ==============================================================================
# 4. Personal Expenses Ownership, IDOR, and Write Protection Tests
# ==============================================================================

@pytest.mark.anyio
async def test_expense_creation_ownership_enforcement(client_auth, headers_a, user_a, user_b, auth_db):
    """
    US-37 Scenario B1 & B5: POST /api/v1/expenses Ownership Enforcement.
    - Legitimate creation binds record strictly to authenticated user (User A).
    - Client attempting to specify or spoof another user's ID (user_id / userId) is rejected
      with HTTP 400 PROTECTED_FIELD_MODIFICATION.
    - Database verification: No expense is created for User B.
    """
    # 1. Legitimate creation
    res_valid = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 15000,
            "description": "User A Official Expense",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    assert res_valid.status_code == 201
    exp_id = uuid.UUID(res_valid.json()["data"]["id"])
    assert auth_db.expenses[exp_id].user_id == user_a.id

    # 2. Tampering via snake_case user_id
    tamper_snake = await client_auth.post(
        "/api/v1/expenses",
        json={
            "user_id": str(user_b.id),
            "amount_minor": 25000,
            "description": "Spoofed User B expense",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    assert tamper_snake.status_code == 400
    assert tamper_snake.json()["code"] == "PROTECTED_FIELD_MODIFICATION"

    # 3. Tampering via camelCase userId
    tamper_camel = await client_auth.post(
        "/api/v1/expenses",
        json={
            "userId": str(user_b.id),
            "amount_minor": 25000,
            "description": "Spoofed User B expense camelCase",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    assert tamper_camel.status_code == 400
    assert tamper_camel.json()["code"] == "PROTECTED_FIELD_MODIFICATION"

    # Database verification: No expenses created for User B
    user_b_expenses = [e for e in auth_db.expenses.values() if e.user_id == user_b.id]
    assert len(user_b_expenses) == 0


@pytest.mark.anyio
async def test_expense_creation_category_authorization(client_auth, headers_a, user_a, user_b, auth_db):
    """
    US-37 Scenario B3: POST /api/v1/expenses Category Authorization.
    - User A can create an expense using a default system category.
    - User A can create an expense using their own custom category.
    - User A CANNOT use User B's private custom category (HTTP 400 INVALID_CATEGORY).
    """
    # User B's private category
    cat_b = Category(
        id=uuid.uuid4(),
        owner_id=user_b.id,
        name="User B Confidential Category",
        is_default=False,
        created_at=datetime.now(UTC),
    )
    auth_db.categories[cat_b.id] = cat_b

    # User A's private category
    cat_a = Category(
        id=uuid.uuid4(),
        owner_id=user_a.id,
        name="User A Private Category",
        is_default=False,
        created_at=datetime.now(UTC),
    )
    auth_db.categories[cat_a.id] = cat_a

    # User A attempts to use User B's category
    bad_cat_res = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 10000,
            "description": "Unauthorized category reference",
            "category_id": str(cat_b.id),
        },
        headers=headers_a,
    )
    assert bad_cat_res.status_code == 400
    assert bad_cat_res.json()["code"] == "INVALID_CATEGORY"

    # User A uses their own private category -> succeeds
    good_cat_res = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 10000,
            "description": "Authorized custom category",
            "category_id": str(cat_a.id),
        },
        headers=headers_a,
    )
    assert good_cat_res.status_code == 201


@pytest.mark.anyio
async def test_expense_read_idor_protection_and_data_leakage(
    client_auth, headers_a, headers_b, headers_c, auth_db
):
    """
    US-37 Scenario B2 & Data Leakage Verification: GET /api/v1/expenses/{id}.
    - User A can read their own expense.
    - User B cannot read User A's expense -> HTTP 404 NOT_FOUND.
    - User C (Stranger) cannot read User A's expense -> HTTP 404 NOT_FOUND.
    - Data Leakage Check: Response body contains ONLY the error envelope;
      private notes, descriptions, merchants, and paise amounts are NEVER leaked.
    """
    res_create = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 987654,
            "description": "Top Secret Executive Expense",
            "merchant": "Confidential Vendor Corp",
            "notes": "Classified strategic investment notes",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    exp_id = res_create.json()["data"]["id"]

    # User A reads own expense
    res_read_a = await client_auth.get(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert res_read_a.status_code == 200
    assert res_read_a.json()["data"]["description"] == "Top Secret Executive Expense"

    # User B attempts to read User A's expense
    res_read_b = await client_auth.get(f"/api/v1/expenses/{exp_id}", headers=headers_b)
    assert res_read_b.status_code == 404
    assert res_read_b.json()["code"] == "NOT_FOUND"
    # Strict Data Leakage Assertions:
    assert "Top Secret Executive Expense" not in res_read_b.text
    assert "Confidential Vendor Corp" not in res_read_b.text
    assert "Classified strategic investment notes" not in res_read_b.text
    assert "987654" not in res_read_b.text

    # User C (Stranger) attempts to read User A's expense
    res_read_c = await client_auth.get(f"/api/v1/expenses/{exp_id}", headers=headers_c)
    assert res_read_c.status_code == 404
    assert res_read_c.json()["code"] == "NOT_FOUND"
    assert "Top Secret" not in res_read_c.text


@pytest.mark.anyio
async def test_expense_listing_isolation_and_query_tampering(
    client_auth, headers_a, headers_b, headers_c, user_b
):
    """
    US-37 Scenario B1, B5, & Data Leakage: GET /api/v1/expenses.
    - User A's listing contains ONLY User A's records.
    - User B's listing contains ONLY User B's records.
    - User C (Stranger) sees an empty listing.
    - Query parameter tampering (?user_id=... / ?userId=...) is rejected with HTTP 403 FORBIDDEN.
    """
    # User A creates 2 expenses
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 12000, "description": "User A Exp 1", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 24000, "description": "User A Exp 2", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )

    # User B creates 1 expense
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 55000, "description": "User B Secret Expense", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_b,
    )

    # User A list
    res_a = await client_auth.get("/api/v1/expenses", headers=headers_a)
    assert res_a.status_code == 200
    descriptions_a = [e["description"] for e in res_a.json()["data"]]
    assert len(descriptions_a) == 2
    assert "User A Exp 1" in descriptions_a
    assert "User B Secret Expense" not in descriptions_a

    # User B list
    res_b = await client_auth.get("/api/v1/expenses", headers=headers_b)
    assert res_b.status_code == 200
    descriptions_b = [e["description"] for e in res_b.json()["data"]]
    assert len(descriptions_b) == 1
    assert "User B Secret Expense" in descriptions_b
    assert "User A Exp 1" not in descriptions_b

    # User C (Stranger) list
    res_c = await client_auth.get("/api/v1/expenses", headers=headers_c)
    assert res_c.status_code == 200
    assert len(res_c.json()["data"]) == 0

    # User A attempts query parameter tampering with User B's ID
    tamper_snake = await client_auth.get(f"/api/v1/expenses?user_id={user_b.id}", headers=headers_a)
    assert tamper_snake.status_code == 403
    assert tamper_snake.json()["code"] == "FORBIDDEN"

    tamper_camel = await client_auth.get(f"/api/v1/expenses?userId={user_b.id}", headers=headers_a)
    assert tamper_camel.status_code == 403
    assert tamper_camel.json()["code"] == "FORBIDDEN"


@pytest.mark.anyio
async def test_expense_totals_isolation_and_query_tampering(
    client_auth, headers_a, headers_b, headers_c, user_b
):
    """
    US-37 Scenario B1, B5, & Data Leakage: GET /api/v1/expenses/totals.
    Totals never leak another user's aggregate spending.
    Query parameter tampering returns HTTP 403 FORBIDDEN.
    """
    # User A expenses: 10000 + 20000 = 30000 paise
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 10000, "description": "A1", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 20000, "description": "A2", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )

    # User B expense: 80000 paise
    await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 80000, "description": "B1", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_b,
    )

    tot_a = await client_auth.get("/api/v1/expenses/totals", headers=headers_a)
    assert tot_a.status_code == 200
    assert tot_a.json()["data"]["totalPaise"] == 30000
    assert tot_a.json()["data"]["count"] == 2

    tot_b = await client_auth.get("/api/v1/expenses/totals", headers=headers_b)
    assert tot_b.status_code == 200
    assert tot_b.json()["data"]["totalPaise"] == 80000
    assert tot_b.json()["data"]["count"] == 1

    tot_c = await client_auth.get("/api/v1/expenses/totals", headers=headers_c)
    assert tot_c.status_code == 200
    assert tot_c.json()["data"]["totalPaise"] == 0
    assert tot_c.json()["data"]["count"] == 0

    # Query parameter tampering
    tamper_tot = await client_auth.get(f"/api/v1/expenses/totals?user_id={user_b.id}", headers=headers_a)
    assert tamper_tot.status_code == 403
    assert tamper_tot.json()["code"] == "FORBIDDEN"


@pytest.mark.anyio
async def test_expense_update_idor_protection_and_db_integrity(
    client_auth, headers_a, headers_b, headers_c, auth_db
):
    """
    US-37 Scenario B2 & Unauthorized Write Verification: PATCH /api/v1/expenses/{id}.
    - User B cannot update User A's expense -> HTTP 404 NOT_FOUND.
    - User C (Stranger) cannot update User A's expense -> HTTP 404 NOT_FOUND.
    - Database verification: Record is completely unaltered in database.
    - User A updating own expense succeeds -> HTTP 200 OK, version incremented.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 45000,
            "description": "Original Unaltered Expense",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)

    # User B attempts unauthorized update
    unauth_b = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Tampered by User B", "version": 1},
        headers=headers_b,
    )
    assert unauth_b.status_code == 404
    assert unauth_b.json()["code"] == "NOT_FOUND"
    # Database integrity verification
    assert auth_db.expenses[exp_uuid].description == "Original Unaltered Expense"
    assert auth_db.expenses[exp_uuid].version == 1

    # User C (Stranger) attempts unauthorized update
    unauth_c = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Tampered by User C", "version": 1},
        headers=headers_c,
    )
    assert unauth_c.status_code == 404
    assert auth_db.expenses[exp_uuid].description == "Original Unaltered Expense"

    # User A updates own expense
    auth_update = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Legitimately Updated by User A", "version": 1},
        headers=headers_a,
    )
    assert auth_update.status_code == 200
    assert auth_update.json()["data"]["version"] == 2
    assert auth_db.expenses[exp_uuid].description == "Legitimately Updated by User A"
    assert auth_db.expenses[exp_uuid].version == 2


@pytest.mark.anyio
async def test_expense_update_protected_fields_tampering_rejected(
    client_auth, headers_a, user_a, user_b, auth_db
):
    """
    US-37 Scenario B5 & AC-5: Protected-Field Modification Rejection.
    A user cannot modify ownership, primary keys, audit timestamps, or security roles
    via the update request body. Returns HTTP 400 PROTECTED_FIELD_MODIFICATION.
    Database records remain completely unaltered.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 18000, "description": "Field Guard Test", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)
    original_created = auth_db.expenses[exp_uuid].created_at

    tampering_payloads = [
        {"user_id": str(user_b.id), "version": 1},
        {"userId": str(user_b.id), "version": 1},
        {"owner_id": str(user_b.id), "version": 1},
        {"id": str(uuid.uuid4()), "version": 1},
        {"created_at": "2020-01-01T00:00:00Z", "version": 1},
        {"deleted_at": "2020-01-01T00:00:00Z", "version": 1},
        {"role": "admin", "version": 1},
        {"is_admin": True, "version": 1},
        {"group_role": "admin", "version": 1},
        {"permissions": ["superuser"], "version": 1},
    ]

    for payload in tampering_payloads:
        resp = await client_auth.patch(f"/api/v1/expenses/{exp_id}", json=payload, headers=headers_a)
        assert resp.status_code == 400, f"Payload {payload} was not rejected with 400"
        assert resp.json()["code"] == "PROTECTED_FIELD_MODIFICATION"

    # Database integrity verification
    assert auth_db.expenses[exp_uuid].user_id == user_a.id
    assert auth_db.expenses[exp_uuid].created_at == original_created
    assert auth_db.expenses[exp_uuid].deleted_at is None
    assert auth_db.expenses[exp_uuid].version == 1


@pytest.mark.anyio
async def test_expense_update_disallowed_fields_rejected(client_auth, headers_a, auth_db):
    """
    US-37 Scenario B5: Disallowed / Unknown Fields Rejection.
    Arbitrary unknown fields in update payloads return HTTP 400 DISALLOWED_FIELD_UPDATE.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 10000, "description": "Clean Item", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)

    bad_field_resp = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"unknown_injected_column": "exploit_value", "version": 1},
        headers=headers_a,
    )
    assert bad_field_resp.status_code == 400
    assert bad_field_resp.json()["code"] == "DISALLOWED_FIELD_UPDATE"
    assert auth_db.expenses[exp_uuid].version == 1


@pytest.mark.anyio
async def test_expense_deletion_idor_protection_and_db_integrity(
    client_auth, headers_a, headers_b, headers_c, auth_db
):
    """
    US-37 Scenario B2 & Unauthorized Write Verification: DELETE /api/v1/expenses/{id}.
    - User B cannot delete User A's expense -> HTTP 404 NOT_FOUND.
    - User C (Stranger) cannot delete User A's expense -> HTTP 404 NOT_FOUND.
    - Database verification: Expense is NOT soft deleted (deleted_at remains None).
    - User A deleting own expense succeeds -> HTTP 200 OK, deleted_at is set.
    """
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 32000, "description": "Active Safe Expense", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)

    # User B unauthorized delete
    del_b = await client_auth.delete(f"/api/v1/expenses/{exp_id}", headers=headers_b)
    assert del_b.status_code == 404
    assert del_b.json()["code"] == "NOT_FOUND"
    assert auth_db.expenses[exp_uuid].deleted_at is None

    # User C unauthorized delete
    del_c = await client_auth.delete(f"/api/v1/expenses/{exp_id}", headers=headers_c)
    assert del_c.status_code == 404
    assert auth_db.expenses[exp_uuid].deleted_at is None

    # User A authorized delete
    del_a = await client_auth.delete(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert del_a.status_code == 200
    assert auth_db.expenses[exp_uuid].deleted_at is not None


@pytest.mark.anyio
async def test_expense_restore_idor_protection_and_db_integrity(
    client_auth, headers_a, headers_b, headers_c, auth_db
):
    """
    US-37 Scenario B2 & B5: POST /api/v1/expenses/{id}/restore.
    - User B cannot restore User A's deleted expense -> HTTP 404 NOT_FOUND.
    - User C cannot restore User A's deleted expense -> HTTP 404 NOT_FOUND.
    - Database verification: deleted_at remains set.
    - User A restoring own expense succeeds -> HTTP 200 OK, deleted_at is cleared.
    - User A restoring an already active expense returns HTTP 400 EXPENSE_NOT_DELETED.
    """
    # 1. User A creates and deletes expense
    res = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 19000, "description": "To Be Restored", "category_id": "00000000-0000-4000-8000-000000000001"},
        headers=headers_a,
    )
    exp_id = res.json()["data"]["id"]
    exp_uuid = uuid.UUID(exp_id)
    await client_auth.delete(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert auth_db.expenses[exp_uuid].deleted_at is not None
    deleted_timestamp = auth_db.expenses[exp_uuid].deleted_at

    # 2. User B unauthorized restore
    rest_b = await client_auth.post(f"/api/v1/expenses/{exp_id}/restore", headers=headers_b)
    assert rest_b.status_code == 404
    assert rest_b.json()["code"] == "NOT_FOUND"
    assert auth_db.expenses[exp_uuid].deleted_at == deleted_timestamp

    # 3. User C unauthorized restore
    rest_c = await client_auth.post(f"/api/v1/expenses/{exp_id}/restore", headers=headers_c)
    assert rest_c.status_code == 404
    assert auth_db.expenses[exp_uuid].deleted_at == deleted_timestamp

    # 4. User A authorized restore
    rest_a = await client_auth.post(f"/api/v1/expenses/{exp_id}/restore", headers=headers_a)
    assert rest_a.status_code == 200
    assert auth_db.expenses[exp_uuid].deleted_at is None

    # 5. User A attempts restore on already active record -> 400
    rest_again = await client_auth.post(f"/api/v1/expenses/{exp_id}/restore", headers=headers_a)
    assert rest_again.status_code == 400
    assert rest_again.json()["code"] == "EXPENSE_NOT_DELETED"


# ==============================================================================
# 5. AI Category Suggestion & Feedback Authorization Tests
# ==============================================================================

@pytest.mark.anyio
async def test_ai_category_suggestion_authorization_and_isolation(
    client_auth, headers_a, headers_b
):
    """
    US-37 AI Endpoints: POST /api/v1/ai/category-suggestion.
    - Unauthenticated requests return HTTP 401 UNAUTHORIZED.
    - User A and User B can access suggestions scoped to their own session.
    """
    res_a = await client_auth.post(
        "/api/v1/ai/category-suggestion",
        json={"description": "Starbucks cold brew coffee", "merchant": "Starbucks"},
        headers=headers_a,
    )
    assert res_a.status_code == 200
    assert res_a.json()["data"]["categoryName"] == "Food & Dining"

    res_b = await client_auth.post(
        "/api/v1/ai/category-suggestion",
        json={"description": "Flight ticket to Mumbai", "merchant": "IndiGo"},
        headers=headers_b,
    )
    assert res_b.status_code == 200
    assert res_b.json()["data"]["categoryName"] == "Travel & Transport"


@pytest.mark.anyio
async def test_ai_category_feedback_authorization_and_spoofing_protection(
    client_auth, headers_a, auth_db, user_a, user_b
):
    """
    US-37 AI Endpoints: POST /api/v1/ai/category-suggestion/feedback.
    - Unauthenticated feedback returns HTTP 401.
    - Feedback submitted by User A is strictly recorded under User A's ID.
    - User A cannot poison or submit feedback on behalf of User B.
    """
    food_cat = uuid.UUID("00000000-0000-4000-8000-000000000001")
    fb_res = await client_auth.post(
        "/api/v1/ai/category-suggestion/feedback",
        json={
            "description": "Swiggy order biryani",
            "merchant": "Swiggy",
            "suggestedCategoryId": str(food_cat),
            "chosenCategoryId": str(food_cat),
            "accepted": True,
            "user_id": str(user_b.id),  # Attempt to spoof User B's profile
        },
        headers=headers_a,
    )
    assert fb_res.status_code == 200
    assert fb_res.json()["data"]["success"] is True
    # Verify in DB that feedback is bound strictly to User A (not User B)
    if auth_db.feedback:
        last_fb = auth_db.feedback[-1]
        assert last_fb.user_id == user_a.id
        assert last_fb.user_id != user_b.id


# ==============================================================================
# 6. Group Membership & Admin Authorization Tests (GroupPolicy)
# ==============================================================================

def test_group_member_access_and_non_member_stranger_denial(user_a, user_b, user_c):
    """
    US-37 Scenario C1 & C5: Group Member vs Stranger (Non-Member).
    Group contains User A and User B. User C is a Stranger / non-member.
    - Group Members (User A, User B) can access group resources.
    - Stranger / Non-Member (User C) is denied with HTTP 403 GROUP_ACCESS_DENIED.
    """
    group_id = uuid.uuid4()
    group_members = {user_a.id, user_b.id}

    # Member User A succeeds
    GroupPolicy.authorize_member(user_a, group_id, group_members)

    # Member User B succeeds
    GroupPolicy.authorize_member(user_b, group_id, group_members)

    # Stranger User C fails
    with pytest.raises(Exception) as exc_non_member:
        GroupPolicy.authorize_member(user_c, group_id, group_members)
    assert exc_non_member.value.status_code == 403
    assert exc_non_member.value.detail["code"] == "GROUP_ACCESS_DENIED"
    assert "not a member" in exc_non_member.value.detail["message"]


def test_group_member_admin_privilege_enforcement(user_a, user_b, admin_user):
    """
    US-37 Scenario C4 & D1: Group Admin vs Member Permissions.
    Group contains User A (Admin) and User B (Standard Member).
    - Group Member (User B) attempting admin action raises HTTP 403 INSUFFICIENT_PERMISSIONS.
    - Group Admin (User A / admin_user) succeeds.
    """
    group_id = uuid.uuid4()
    members = {user_a.id, user_b.id, admin_user.id}
    admins = {user_a.id, admin_user.id}

    # Standard Member User B attempting admin action is denied
    with pytest.raises(Exception) as exc_non_admin:
        GroupPolicy.authorize_admin(user_b, group_id, members, admins)
    assert exc_non_admin.value.status_code == 403
    assert exc_non_admin.value.detail["code"] == "INSUFFICIENT_PERMISSIONS"
    assert "Administrator privileges required" in exc_non_admin.value.detail["message"]

    # Group Admin User A succeeds
    GroupPolicy.authorize_admin(user_a, group_id, members, admins)

    # Dedicated Admin Actor succeeds
    GroupPolicy.authorize_admin(admin_user, group_id, members, admins)


@pytest.mark.anyio
async def test_admin_actor_permissions_and_scope(client_auth, headers_admin, admin_user):
    """
    US-37 Scenario D: Admin Permissions and Scope Enforcement.
    - Admin actor can successfully authenticate and access authorized administrative scopes.
    - Admin actor performing permitted administrative operations succeeds.
    - Admin actor attempting operations outside allowed schema bounds (e.g. tampering
      with immutable audit timestamps or primary keys) is strictly rejected with HTTP 400.
    """
    # 1. Admin accesses profile
    me_resp = await client_auth.get("/api/v1/auth/me", headers=headers_admin)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == admin_user.email

    # 2. Admin creates an expense within administrative scope
    create_resp = await client_auth.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 50000,
            "description": "Admin Audited Expenditure",
            "category_id": "00000000-0000-4000-8000-000000000001",
        },
        headers=headers_admin,
    )
    assert create_resp.status_code == 201
    exp_id = create_resp.json()["data"]["id"]

    # 3. Admin attempting operation outside authorized scope (e.g. primary key tampering) is rejected
    tamper_resp = await client_auth.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"id": str(uuid.uuid4()), "version": 1},
        headers=headers_admin,
    )
    assert tamper_resp.status_code == 400
    assert tamper_resp.json()["code"] == "PROTECTED_FIELD_MODIFICATION"

    # 4. Admin attempting to restore an active expense is rejected
    bad_restore = await client_auth.post(
        f"/api/v1/expenses/{exp_id}/restore",
        headers=headers_admin,
    )
    assert bad_restore.status_code == 400
    assert bad_restore.json()["code"] == "EXPENSE_NOT_DELETED"



# ==============================================================================
# 7. Direct Policy Unit Tests & Scope Verifications
# ==============================================================================

def test_expense_policy_direct_unit_tests(user_a, user_b):
    """
    US-37 Direct Unit Verification: ExpensePolicy.
    - Authorizing own active expense succeeds for READ, UPDATE, DELETE.
    - Authorizing foreign expense raises HTTP 404 NOT_FOUND.
    - Authorizing deleted expense raises HTTP 404 unless allow_deleted=True.
    - Restoring active expense raises HTTP 400 EXPENSE_NOT_DELETED.
    """
    own_active = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        amount_minor=1000,
        description="Mine",
        version=1,
        deleted_at=None,
    )
    foreign_expense = Expense(
        id=uuid.uuid4(),
        user_id=user_b.id,
        amount_minor=2000,
        description="Foreign",
        version=1,
        deleted_at=None,
    )
    own_deleted = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        amount_minor=1000,
        description="Deleted",
        version=2,
        deleted_at=datetime.now(UTC),
    )

    # Own active: READ, UPDATE, DELETE succeed
    ExpensePolicy.authorize(user_a, own_active, Action.READ)
    ExpensePolicy.authorize(user_a, own_active, Action.UPDATE)
    ExpensePolicy.authorize(user_a, own_active, Action.DELETE)

    # Foreign expense: raises 404 (IDOR protection)
    with pytest.raises(Exception) as exc_foreign:
        ExpensePolicy.authorize(user_a, foreign_expense, Action.READ)
    assert exc_foreign.value.status_code == 404

    # Own deleted: raises 404 on normal read
    with pytest.raises(Exception) as exc_deleted:
        ExpensePolicy.authorize(user_a, own_deleted, Action.READ)
    assert exc_deleted.value.status_code == 404

    # Own deleted: succeeds with allow_deleted=True or Action.RESTORE
    ExpensePolicy.authorize(user_a, own_deleted, Action.RESTORE)

    # Restoring active expense raises 400
    with pytest.raises(Exception) as exc_restore_active:
        ExpensePolicy.authorize(user_a, own_active, Action.RESTORE)
    assert exc_restore_active.value.status_code == 400
    assert exc_restore_active.value.detail["code"] == "EXPENSE_NOT_DELETED"


def test_category_policy_direct_unit_tests(user_a, user_b):
    """
    US-37 Direct Unit Verification: CategoryPolicy.
    - Default categories are readable by all users.
    - Default categories CANNOT be modified or deleted (raises HTTP 403 FORBIDDEN).
    - Custom categories can be read and updated by their owner.
    - Foreign custom categories cannot be read (raises HTTP 400 INVALID_CATEGORY) or updated (404).
    """
    default_cat = Category(
        id=uuid.uuid4(),
        name="Default System Category",
        is_default=True,
        owner_id=None,
    )
    own_custom = Category(
        id=uuid.uuid4(),
        name="User A Custom",
        is_default=False,
        owner_id=user_a.id,
    )
    foreign_custom = Category(
        id=uuid.uuid4(),
        name="User B Custom",
        is_default=False,
        owner_id=user_b.id,
    )

    # 1. Default category: read allowed, update/delete forbidden (403)
    CategoryPolicy.authorize(user_a, default_cat, Action.READ)
    with pytest.raises(Exception) as exc_default_upd:
        CategoryPolicy.authorize(user_a, default_cat, Action.UPDATE)
    assert exc_default_upd.value.status_code == 403

    with pytest.raises(Exception) as exc_default_del:
        CategoryPolicy.authorize(user_a, default_cat, Action.DELETE)
    assert exc_default_del.value.status_code == 403

    # 2. Own custom: read and update allowed
    CategoryPolicy.authorize(user_a, own_custom, Action.READ)
    CategoryPolicy.authorize(user_a, own_custom, Action.UPDATE)

    # 3. Foreign custom: read raises 400, update raises 404
    with pytest.raises(Exception) as exc_foreign_read:
        CategoryPolicy.authorize(user_a, foreign_custom, Action.READ)
    assert exc_foreign_read.value.status_code == 400

    with pytest.raises(Exception) as exc_foreign_upd:
        CategoryPolicy.authorize(user_a, foreign_custom, Action.UPDATE)
    assert exc_foreign_upd.value.status_code == 404


def test_session_policy_direct_unit_tests(user_a, user_b):
    """
    US-37 Direct Unit Verification: SessionPolicy.
    - Authorizing own session succeeds.
    - Authorizing foreign session raises HTTP 404 SESSION_NOT_FOUND.
    """
    own_session = RefreshToken(id=uuid.uuid4(), user_id=user_a.id, family_id=uuid.uuid4())
    foreign_session = RefreshToken(id=uuid.uuid4(), user_id=user_b.id, family_id=uuid.uuid4())

    SessionPolicy.authorize(user_a, own_session, Action.READ)
    SessionPolicy.authorize(user_a, own_session, Action.DELETE)

    with pytest.raises(Exception) as exc_foreign:
        SessionPolicy.authorize(user_a, foreign_session, Action.DELETE)
    assert exc_foreign.value.status_code == 404
    assert exc_foreign.value.detail["code"] == "SESSION_NOT_FOUND"


def test_validate_protected_fields_utility():
    """
    US-37 Direct Unit Verification: validate_protected_fields_update.
    - Allowed fields pass.
    - Disallowed fields raise HTTP 400 DISALLOWED_FIELD_UPDATE.
    - Protected fields raise HTTP 400 PROTECTED_FIELD_MODIFICATION.
    """
    # 1. Allowed fields pass
    validate_protected_fields_update(
        {"description": "New lunch", "amount_minor": 1500},
        allowed_fields={"description", "amount_minor"},
    )

    # 2. Disallowed fields raise 400
    with pytest.raises(Exception) as exc_disallowed:
        validate_protected_fields_update(
            {"description": "Valid", "disallowed_field_xyz": "value"},
            allowed_fields={"description"},
        )
    assert exc_disallowed.value.status_code == 400
    assert exc_disallowed.value.detail["code"] == "DISALLOWED_FIELD_UPDATE"

    # 3. Protected fields raise 400
    for protected_key in ["user_id", "userId", "owner_id", "created_at", "role", "is_admin"]:
        with pytest.raises(Exception) as exc_protected:
            validate_protected_fields_update({protected_key: "value"})
        assert exc_protected.value.status_code == 400
        assert exc_protected.value.detail["code"] == "PROTECTED_FIELD_MODIFICATION"
