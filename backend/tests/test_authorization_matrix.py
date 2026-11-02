"""
Authorization Test Matrix — Smart Expense Splitter & Tracker (Coinscious).
Issue T-17 / US-37 (#43).

This suite provides systematic coverage of every endpoint in the actual
OpenAPI contract (backend/openapi.json) across the three applicable actors:

  Actor 1 — Stranger / Unauthenticated  (no credentials)
  Actor 2 — Non-owner                   (valid token, but different user)
  Actor 3 — Owner / legitimate caller   (valid token, correct ownership)

No admin role exists in the current codebase; GroupPolicy is tested via
direct unit calls rather than HTTP endpoints that do not yet exist.

All tests use the project's standard FakeDB pattern (SQLAlchemy statement
interception in memory) so they run without a live database.  This follows
the same conventions established in test_authorization.py and test_expenses.py.

Dependency: T-16 (backend/app/core/authorization.py) is required.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_refresh_token
from app.main import app as main_app
from app.models.category import Category
from app.models.expense import Expense
from app.models.idempotency import IdempotencyRecord
from app.models.refresh_token import RefreshToken
from app.models.user import User
from tests.auth_matrix_data import OPENAPI_AUTHORIZATION_MATRIX, EndpointMatrixEntry


# ==============================================================================
# In-memory test database — mirrors the pattern used in test_authorization.py
# ==============================================================================

class MatrixDB:
    """In-memory store for all model types used in authorization tests."""

    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.idempotency_records: dict[tuple[uuid.UUID, str], IdempotencyRecord] = {}
        self.tokens: dict[uuid.UUID, RefreshToken] = {}


class _Scalars:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class _Result:
    def __init__(self, items=None, rowcount=1, tuple_res=None):
        self._items = list(items) if items else []
        self.rowcount = rowcount
        self._tuple_res = tuple_res

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar_one(self):
        return self._items[0] if self._items else 0

    def scalar(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return _Scalars(self._items)

    def one(self):
        if self._tuple_res is not None:
            return self._tuple_res
        return self._items[0] if self._items else (0, 0)


class MatrixSession:
    """
    SQLAlchemy-shaped async session that intercepts compiled statements
    and routes them against in-memory dictionaries.

    Key implementation notes
    ─────────────────────────
    • token_hash filtering: the logout endpoint queries
      ``WHERE RefreshToken.token_hash == hash_refresh_token(raw_token)``.
      The FakeDB must therefore honour hash_val filtering so that the
      CREDENTIAL_MISMATCH security check is exercised correctly.
    • update refresh_tokens: two variants are executed —
        (a) WHERE family_id == ? (revoke a family)
        (b) WHERE user_id == ? AND is_revoked == false  (logout all)
      Both are handled.
    """

    def __init__(self, db: MatrixDB):
        self.db = db
        self._pending: list = []

    def add(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        self._pending.append(obj)

    async def commit(self):
        for obj in self._pending:
            if isinstance(obj, User):
                self.db.users[obj.id] = obj
            elif isinstance(obj, Category):
                self.db.categories[obj.id] = obj
            elif isinstance(obj, Expense):
                self.db.expenses[obj.id] = obj
            elif isinstance(obj, RefreshToken):
                self.db.tokens[obj.id] = obj
            elif isinstance(obj, IdempotencyRecord):
                key = (obj.user_id, obj.key)
                existing = self.db.idempotency_records.get(key)
                if existing is not None and existing.id != obj.id:
                    raise IntegrityError(
                        "unique constraint uq_idempotency_records_user_key",
                        params={},
                        orig=Exception(),
                    )
                self.db.idempotency_records[key] = obj
        self._pending.clear()

    async def rollback(self):
        self._pending.clear()

    async def refresh(self, obj):
        pass

    async def flush(self):
        await self.commit()

    async def execute(self, stmt):
        # Flush pending objects before every query so that newly added
        # records are immediately visible to subsequent SELECT statements.
        await self.commit()

        sql = str(stmt).lower()
        params = stmt.compile().params

        # ── SELECT users ─────────────────────────────────────────────────────
        if "from users" in sql:
            id_val = next((v for k, v in params.items() if "id" in k), None)
            if id_val is not None:
                matched = [u for u in self.db.users.values() if u.id == id_val]
                return _Result(matched)
            email_val = next((v for k, v in params.items() if "email" in k), None)
            if email_val is not None:
                matched = [
                    u for u in self.db.users.values()
                    if u.email.lower() == str(email_val).lower()
                ]
                return _Result(matched)
            return _Result(list(self.db.users.values()))

        # ── SELECT categories ─────────────────────────────────────────────────
        if "from categories" in sql:
            cat_id = next((v for k, v in params.items() if "id_1" in k or "id" in k), None)
            user_id = next(
                (v for k, v in params.items() if "owner_id" in k or "user" in k), None
            )
            matched = []
            for c in self.db.categories.values():
                if cat_id is not None and c.id != cat_id:
                    continue
                if c.is_default or (user_id is not None and c.owner_id == user_id):
                    matched.append(c)
            return _Result(matched)

        # ── SELECT idempotency_records ────────────────────────────────────────
        if "from idempotency_records" in sql:
            user_id = next((v for k, v in params.items() if "user_id" in k), None)
            key_val = next((v for k, v in params.items() if k == "key"), None)
            matched = [
                rec
                for (uid, k), rec in self.db.idempotency_records.items()
                if (user_id is None or uid == user_id)
                and (key_val is None or k == key_val)
            ]
            return _Result(matched)

        # ── UPDATE expenses ───────────────────────────────────────────────────
        if sql.startswith("update expenses"):
            exp_id = params.get("id_1") or params.get("id")
            user_id = params.get("user_id_1") or params.get("user_id")
            exp_version = (
                params.get("version_1") if "version_1" in params else params.get("version")
            )
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
                return _Result(rowcount=0)
            mutable = {
                "amount_minor", "description", "category_id", "expense_date",
                "notes", "merchant", "payment_mode", "receipt_id", "version",
                "updated_at",
            }
            for col, val in params.items():
                if col in mutable:
                    setattr(target, col, val)
            return _Result(rowcount=1)

        # ── Aggregate: count / sum over expenses ──────────────────────────────
        if "count(expenses.id)" in sql or "coalesce(sum(expenses.amount_minor)" in sql:
            user_id = params.get("user_id_1") or params.get("user_id")
            matched = [
                e for e in self.db.expenses.values()
                if e.user_id == user_id and e.deleted_at is None
            ]
            total_paise = sum(e.amount_minor for e in matched)
            count = len(matched)
            if "coalesce(sum" in sql:
                return _Result(tuple_res=(total_paise, count))
            return _Result([count])

        # ── SELECT expenses ───────────────────────────────────────────────────
        if "from expenses" in sql:
            exp_id = params.get("id_1") or (
                params.get("id") if "expenses.id" in sql else None
            )
            user_id = params.get("user_id_1") or params.get("user_id")
            matched = list(self.db.expenses.values())
            if exp_id is not None:
                matched = [e for e in matched if e.id == exp_id]
            if user_id is not None:
                matched = [e for e in matched if e.user_id == user_id]
            if "deleted_at is null" in sql:
                matched = [e for e in matched if e.deleted_at is None]
            matched.sort(key=lambda x: (x.expense_date, x.created_at), reverse=True)
            return _Result(matched)

        # ── SELECT refresh_tokens ─────────────────────────────────────────────
        if "from refresh_tokens" in sql:
            matched = list(self.db.tokens.values())
            # Filter by token_hash if present (used by logout / refresh)
            hash_val = next(
                (v for k, v in params.items() if "token_hash" in k or "hash" in k),
                None,
            )
            if hash_val is not None:
                matched = [t for t in matched if t.token_hash == hash_val]
            else:
                fam_or_id = next(
                    (v for k, v in params.items() if "family" in k or "id" in k), None
                )
                if fam_or_id is not None:
                    matched = [
                        t for t in matched
                        if t.family_id == fam_or_id or t.id == fam_or_id
                    ]
            user_id = next((v for k, v in params.items() if "user" in k), None)
            if user_id is not None:
                matched = [t for t in matched if t.user_id == user_id]
            return _Result(matched)

        # ── UPDATE refresh_tokens ─────────────────────────────────────────────
        if "update refresh_tokens" in sql:
            fam_val = next((v for k, v in params.items() if "family" in k), None)
            user_val = next((v for k, v in params.items() if "user_id" in k), None)
            if fam_val is not None:
                for t in self.db.tokens.values():
                    if t.family_id == fam_val:
                        t.is_revoked = True
            elif user_val is not None:
                for t in self.db.tokens.values():
                    if t.user_id == user_val and not t.is_revoked:
                        t.is_revoked = True
            return _Result([])

        return _Result([])


# ==============================================================================
# Pytest fixtures
# ==============================================================================

DEFAULT_CAT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture
def matrix_db():
    """Fresh in-memory database seeded with one default category."""
    db = MatrixDB()
    db.categories[DEFAULT_CAT_ID] = Category(
        id=DEFAULT_CAT_ID,
        name="Food & Dining",
        is_default=True,
        owner_id=None,
        created_at=datetime.now(UTC),
    )
    return db


@pytest.fixture
def user_a(matrix_db):
    user = User(
        id=uuid.uuid4(),
        email="matrix_user_a@example.com",
        name="Matrix User A",
        hashed_password="hashed_pw_a",
        is_active=True,
    )
    matrix_db.users[user.id] = user
    return user


@pytest.fixture
def user_b(matrix_db):
    user = User(
        id=uuid.uuid4(),
        email="matrix_user_b@example.com",
        name="Matrix User B",
        hashed_password="hashed_pw_b",
        is_active=True,
    )
    matrix_db.users[user.id] = user
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


def create_matrix_test_app() -> FastAPI:
    """
    Creates a FastAPI test application for the authorization matrix.
    Wires the merged T-16 authorization routes (from app.api.expenses)
    so tests can verify the complete authorization matrix as specified in US-37.
    """
    from app.api.v1.endpoints import ai, auth, health
    try:
        from app.api.expenses import router as expenses_router
    except ImportError:
        from app.api.v1.endpoints import expenses as expenses_router

    test_router = APIRouter()
    test_router.include_router(health.router, tags=["Health"])
    test_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
    test_router.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
    test_router.include_router(ai.router, prefix="/ai", tags=["AI"])

    test_app = FastAPI(title=settings.PROJECT_NAME, version=settings.VERSION)
    test_app.exception_handlers = dict(main_app.exception_handlers)
    test_app.include_router(test_router, prefix="/api/v1")
    return test_app


matrix_app = create_matrix_test_app()


@pytest.fixture
async def client(matrix_db):
    """AsyncClient wired to the MatrixSession FakeDB override."""

    async def _override_get_db():
        yield MatrixSession(matrix_db)

    matrix_app.dependency_overrides[get_db] = _override_get_db
    main_app.dependency_overrides[get_db] = _override_get_db

    with patch("app.api.v1.endpoints.health.check_database_connection", return_value=(True, None)):
        transport = ASGITransport(app=matrix_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac

    matrix_app.dependency_overrides.clear()
    main_app.dependency_overrides.clear()


# ==============================================================================
# 1. OpenAPI Completeness / Coverage Guard
# ==============================================================================

def test_openapi_contract_completeness():
    """
    Acceptance Criterion 1 — Every endpoint in the current OpenAPI contract
    has a corresponding entry in OPENAPI_AUTHORIZATION_MATRIX.

    This test FAILS if:
    • A new endpoint is added to openapi.json without adding a matrix entry.
    • A matrix entry references an endpoint that no longer exists.
    """
    openapi_path = Path(__file__).resolve().parent.parent / "openapi.json"
    assert openapi_path.exists(), f"OpenAPI spec not found at {openapi_path}"

    with openapi_path.open(encoding="utf-8") as fh:
        spec = json.load(fh)

    openapi_ops: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            openapi_ops.add((method.upper(), path))

    matrix_ops: set[tuple[str, str]] = {
        (e.method.upper(), e.path) for e in OPENAPI_AUTHORIZATION_MATRIX
    }

    missing = openapi_ops - matrix_ops
    extra = matrix_ops - openapi_ops

    assert not missing, (
        f"These OpenAPI operations have no authorization classification:\n"
        + "\n".join(f"  {m} {p}" for m, p in sorted(missing))
    )
    assert not extra, (
        f"These matrix entries do not correspond to any OpenAPI operation:\n"
        + "\n".join(f"  {m} {p}" for m, p in sorted(extra))
    )
    assert len(matrix_ops) == 16, (
        f"Expected 16 classified operations, found {len(matrix_ops)}"
    )


# ==============================================================================
# 2. Actor 1 — Stranger / Unauthenticated (parametrised over every endpoint)
# ==============================================================================

@pytest.mark.anyio
@pytest.mark.parametrize(
    "entry",
    OPENAPI_AUTHORIZATION_MATRIX,
    ids=lambda e: f"{e.method}_{e.path.replace('/', '_').strip('_')}",
)
async def test_stranger_access(client: AsyncClient, entry: EndpointMatrixEntry):
    """
    Verifies the exact HTTP status returned to a caller who supplies NO
    credentials at all.

    • Protected endpoints must return 401 with code UNAUTHORIZED or INVALID_TOKEN.
    • Public endpoints must return the documented stranger_status.
    """
    dummy = str(uuid.uuid4())
    path = entry.path.replace("{expense_id}", dummy).replace("{session_id}", dummy)

    body = None
    if entry.method in ("POST", "PATCH"):
        if "signup" in path or "register" in path:
            body = {
                "name": "Stranger",
                "email": f"stranger_{uuid.uuid4().hex[:8]}@test.com",
                "password": "StrongPass1!",
            }
        elif "login" in path:
            body = {"email": "nobody@test.com", "password": "WrongPassword1!"}
        elif "refresh" in path:
            body = {"refresh_token": "definitely_invalid_token_string"}
        elif "logout" in path:
            body = {}  # empty body → no token to revoke
        elif "expenses" in path:
            body = {
                "amount_minor": 10000,
                "description": "Stranger expense",
                "category_id": str(DEFAULT_CAT_ID),
            }

    res = await client.request(entry.method, path, json=body)

    if entry.auth_required:
        assert res.status_code == 401, (
            f"{entry.method} {entry.path}: expected 401 for unauthenticated request, "
            f"got {res.status_code}. Body: {res.text[:300]}"
        )
        data = res.json()
        assert data.get("code") in ("UNAUTHORIZED", "INVALID_TOKEN"), (
            f"Unexpected error code '{data.get('code')}' for {entry.method} {entry.path}"
        )
        assert data.get("isRetryable") is False
    else:
        assert res.status_code == entry.stranger_status, (
            f"{entry.method} {entry.path}: expected {entry.stranger_status} for "
            f"unauthenticated public request, got {res.status_code}. "
            f"Body: {res.text[:300]}"
        )


# ==============================================================================
# 3. Invalid and expired token rejection
# ==============================================================================

@pytest.mark.anyio
async def test_invalid_token_rejected_on_all_protected_endpoints(
    client: AsyncClient, user_a: User
):
    """
    Verifies that a structurally invalid JWT (not just absent) is always
    rejected with 401 INVALID_TOKEN across every protected route.
    """
    protected = [
        ("GET",    "/api/v1/auth/me"),
        ("GET",    "/api/v1/auth/sessions"),
        ("DELETE", f"/api/v1/auth/sessions/{uuid.uuid4()}"),
        ("POST",   "/api/v1/expenses"),
        ("GET",    "/api/v1/expenses"),
        ("GET",    "/api/v1/expenses/totals"),
        ("GET",    f"/api/v1/expenses/{uuid.uuid4()}"),
        ("PATCH",  f"/api/v1/expenses/{uuid.uuid4()}"),
        ("DELETE", f"/api/v1/expenses/{uuid.uuid4()}"),
        ("POST",   f"/api/v1/expenses/{uuid.uuid4()}/restore"),
    ]
    bad_headers = {"Authorization": "Bearer not.a.valid.jwt.at.all"}
    for method, path in protected:
        res = await client.request(method, path, headers=bad_headers)
        assert res.status_code == 401, (
            f"{method} {path}: expected 401 for invalid token, got {res.status_code}"
        )
        assert res.json().get("code") == "INVALID_TOKEN", (
            f"{method} {path}: expected INVALID_TOKEN code"
        )


@pytest.mark.anyio
async def test_expired_token_rejected_on_all_protected_endpoints(
    client: AsyncClient, user_a: User
):
    """
    Verifies that an expired (but structurally valid) JWT is rejected
    with 401 TOKEN_EXPIRED across every protected route.
    """
    now = datetime.now(UTC)
    expired_payload = {
        "sub":   str(user_a.id),
        "email": user_a.email,
        "type":  "access",
        "exp":   int((now - timedelta(hours=1)).timestamp()),
        "iat":   int((now - timedelta(hours=2)).timestamp()),
        "iss":   settings.JWT_ISSUER,
        "aud":   settings.JWT_AUDIENCE,
        "jti":   str(uuid.uuid4()),
    }
    expired_token = jwt.encode(
        expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    exp_headers = {"Authorization": f"Bearer {expired_token}"}

    protected = [
        ("GET",    "/api/v1/auth/me"),
        ("GET",    "/api/v1/auth/sessions"),
        ("DELETE", f"/api/v1/auth/sessions/{uuid.uuid4()}"),
        ("GET",    "/api/v1/expenses"),
        ("GET",    "/api/v1/expenses/totals"),
        ("GET",    f"/api/v1/expenses/{uuid.uuid4()}"),
    ]
    for method, path in protected:
        res = await client.request(method, path, headers=exp_headers)
        assert res.status_code == 401, (
            f"{method} {path}: expected 401 for expired token, got {res.status_code}"
        )
        assert res.json().get("code") == "TOKEN_EXPIRED", (
            f"{method} {path}: expected TOKEN_EXPIRED code"
        )


# ==============================================================================
# 4. Actor 2 — Authenticated Non-Owner: Cross-User Isolation (IDOR)
# ==============================================================================

@pytest.mark.anyio
async def test_cross_user_expense_read_returns_404(
    client: AsyncClient,
    headers_a: dict,
    headers_b: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    User B cannot read User A's private expense.
    Returns 404 NOT_FOUND (conceals existence — prevents IDOR).
    Database record is not exposed.
    """
    exp_a = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        category_id=DEFAULT_CAT_ID,
        amount_minor=75000,
        description="User A Confidential Purchase",
        expense_date=datetime.now(UTC).date(),
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )
    matrix_db.expenses[exp_a.id] = exp_a

    res = await client.get(f"/api/v1/expenses/{exp_a.id}", headers=headers_b)
    assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["code"] == "NOT_FOUND"
    # Confirm the confidential description is not exposed in the response body
    assert "Confidential" not in res.text


@pytest.mark.anyio
async def test_cross_user_expense_patch_returns_404_and_leaves_db_unchanged(
    client: AsyncClient,
    headers_b: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    User B cannot update User A's expense.
    Returns 404. The expense's description in the database must not change.
    """
    exp_a = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        category_id=DEFAULT_CAT_ID,
        amount_minor=20000,
        description="Original description, must not change",
        expense_date=datetime.now(UTC).date(),
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )
    matrix_db.expenses[exp_a.id] = exp_a

    res = await client.patch(
        f"/api/v1/expenses/{exp_a.id}",
        json={"description": "Tampered by User B", "version": 1},
        headers=headers_b,
    )
    assert res.status_code == 404
    assert matrix_db.expenses[exp_a.id].description == "Original description, must not change"


@pytest.mark.anyio
async def test_cross_user_expense_delete_returns_404_and_leaves_db_unchanged(
    client: AsyncClient,
    headers_b: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    User B cannot soft-delete User A's expense.
    Returns 404. The deleted_at timestamp must remain None.
    """
    exp_a = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        category_id=DEFAULT_CAT_ID,
        amount_minor=15000,
        description="Expense B must not be able to delete",
        expense_date=datetime.now(UTC).date(),
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )
    matrix_db.expenses[exp_a.id] = exp_a

    res = await client.delete(f"/api/v1/expenses/{exp_a.id}", headers=headers_b)
    assert res.status_code == 404
    assert matrix_db.expenses[exp_a.id].deleted_at is None, (
        "Expense must not be soft-deleted by a non-owner"
    )


@pytest.mark.anyio
async def test_cross_user_expense_restore_returns_404_and_leaves_db_unchanged(
    client: AsyncClient,
    headers_b: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    User B cannot restore User A's soft-deleted expense.
    Returns 404. The deleted_at timestamp must remain set.
    """
    deletion_time = datetime.now(UTC)
    exp_a = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        category_id=DEFAULT_CAT_ID,
        amount_minor=15000,
        description="Soft-deleted expense that B cannot restore",
        expense_date=datetime.now(UTC).date(),
        version=1,
        created_at=datetime.now(UTC) - timedelta(days=1),
        updated_at=datetime.now(UTC),
        deleted_at=deletion_time,
    )
    matrix_db.expenses[exp_a.id] = exp_a

    res = await client.post(f"/api/v1/expenses/{exp_a.id}/restore", headers=headers_b)
    assert res.status_code == 404
    assert matrix_db.expenses[exp_a.id].deleted_at == deletion_time, (
        "Expense deleted_at must not be cleared by a non-owner restore attempt"
    )


@pytest.mark.anyio
async def test_cross_user_session_revoke_returns_404_and_leaves_session_active(
    client: AsyncClient,
    headers_b: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    User B cannot revoke User A's active session via DELETE /sessions/{id}.
    Returns 404 SESSION_NOT_FOUND. Session remains active (is_revoked stays False).
    """
    sess_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token("raw_token_for_session_a"),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        is_revoked=False,
    )
    matrix_db.tokens[sess_a.id] = sess_a

    res = await client.delete(
        f"/api/v1/auth/sessions/{sess_a.family_id}", headers=headers_b
    )
    assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"
    assert res.json()["code"] == "SESSION_NOT_FOUND"
    assert matrix_db.tokens[sess_a.id].is_revoked is False, (
        "Session must remain active after non-owner revocation attempt"
    )


@pytest.mark.anyio
async def test_cross_user_logout_with_foreign_token_returns_403(
    client: AsyncClient,
    headers_b: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    User B (authenticated) cannot revoke User A's refresh token via POST /auth/logout.
    Sending User A's raw refresh token while authenticated as User B must return
    403 CREDENTIAL_MISMATCH, and User A's session must remain active.

    The fix is critical: the DB stores hash_refresh_token(raw) so that the
    logout endpoint's hash_refresh_token(payload.refresh_token) lookup matches.
    """
    raw_token_a = "raw_refresh_token_belonging_to_user_a"
    sess_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        # Store the SHA-256 hash so the endpoint can find the record
        token_hash=hash_refresh_token(raw_token_a),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        is_revoked=False,
    )
    matrix_db.tokens[sess_a.id] = sess_a

    # User B is authenticated and sends User A's raw refresh token
    res = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": raw_token_a},
        headers=headers_b,
    )
    assert res.status_code == 403, (
        f"Expected 403 CREDENTIAL_MISMATCH, got {res.status_code}: {res.text}"
    )
    assert res.json()["code"] == "CREDENTIAL_MISMATCH"
    assert matrix_db.tokens[sess_a.id].is_revoked is False, (
        "User A's session must remain active after the CREDENTIAL_MISMATCH rejection"
    )


# ==============================================================================
# 5. List and totals data isolation + query-parameter injection defence
# ==============================================================================

@pytest.mark.anyio
async def test_list_expenses_returns_only_caller_expenses(
    client: AsyncClient,
    headers_a: dict,
    headers_b: dict,
    user_a: User,
    user_b: User,
    matrix_db: MatrixDB,
):
    """
    GET /expenses returns only the authenticated caller's expenses.
    User A's expenses must never appear in User B's list response.
    """
    exp_a = Expense(
        id=uuid.uuid4(), user_id=user_a.id, category_id=DEFAULT_CAT_ID,
        amount_minor=15000, description="User A Private Flight",
        expense_date=datetime.now(UTC).date(), version=1,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None,
    )
    exp_b = Expense(
        id=uuid.uuid4(), user_id=user_b.id, category_id=DEFAULT_CAT_ID,
        amount_minor=50000, description="User B Hotel",
        expense_date=datetime.now(UTC).date(), version=1,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None,
    )
    matrix_db.expenses[exp_a.id] = exp_a
    matrix_db.expenses[exp_b.id] = exp_b

    res_b = await client.get("/api/v1/expenses", headers=headers_b)
    assert res_b.status_code == 200
    ids_returned = [item["id"] for item in res_b.json()["data"]]
    assert str(exp_b.id) in ids_returned, "User B's own expense must appear"
    assert str(exp_a.id) not in ids_returned, "User A's expense must not leak to User B"
    assert "User A" not in res_b.text


@pytest.mark.anyio
async def test_totals_returns_only_caller_amounts(
    client: AsyncClient,
    headers_a: dict,
    headers_b: dict,
    user_a: User,
    user_b: User,
    matrix_db: MatrixDB,
):
    """
    GET /expenses/totals returns spending totals scoped strictly to the caller.
    User B's total must not include User A's expenses.
    """
    exp_a = Expense(
        id=uuid.uuid4(), user_id=user_a.id, category_id=DEFAULT_CAT_ID,
        amount_minor=99999, description="User A Expense",
        expense_date=datetime.now(UTC).date(), version=1,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None,
    )
    exp_b = Expense(
        id=uuid.uuid4(), user_id=user_b.id, category_id=DEFAULT_CAT_ID,
        amount_minor=30000, description="User B Expense",
        expense_date=datetime.now(UTC).date(), version=1,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None,
    )
    matrix_db.expenses[exp_a.id] = exp_a
    matrix_db.expenses[exp_b.id] = exp_b

    res = await client.get("/api/v1/expenses/totals", headers=headers_b)
    assert res.status_code == 200
    totals = res.json()["data"]
    assert totals["totalPaise"] == 30000, (
        f"User B's total should be 30000, not {totals['totalPaise']}"
    )
    assert totals["count"] == 1


@pytest.mark.anyio
async def test_query_parameter_user_id_injection_rejected(
    client: AsyncClient,
    headers_b: dict,
    user_a: User,
):
    """
    Passing ?user_id=<foreign_id> on list or totals endpoints is rejected
    with 403 FORBIDDEN regardless of who is authenticated.
    """
    res_list = await client.get(
        f"/api/v1/expenses?user_id={user_a.id}", headers=headers_b
    )
    assert res_list.status_code == 403
    assert res_list.json()["code"] == "FORBIDDEN"

    res_totals = await client.get(
        f"/api/v1/expenses/totals?user_id={user_a.id}", headers=headers_b
    )
    assert res_totals.status_code == 403
    assert res_totals.json()["code"] == "FORBIDDEN"


# ==============================================================================
# 6. Protected-Field Updates — Ownership Forgery and Privilege Escalation
# ==============================================================================

@pytest.mark.anyio
async def test_protected_field_ownership_forgery_via_patch_rejected(
    client: AsyncClient,
    headers_a: dict,
    user_a: User,
    user_b: User,
    matrix_db: MatrixDB,
):
    """
    Sending ownership-related fields in a PATCH payload must be rejected
    with 400 PROTECTED_FIELD_MODIFICATION. The database record must not change.
    """
    exp = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        category_id=DEFAULT_CAT_ID,
        amount_minor=10000,
        description="Ownership test expense",
        expense_date=datetime.now(UTC).date(),
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )
    matrix_db.expenses[exp.id] = exp

    for field in ("user_id", "userId", "owner_id", "ownerId", "creator_id"):
        res = await client.patch(
            f"/api/v1/expenses/{exp.id}",
            json={field: str(user_b.id), "version": 1},
            headers=headers_a,
        )
        assert res.status_code == 400, (
            f"Field '{field}' should be rejected with 400, got {res.status_code}"
        )
        assert res.json()["code"] == "PROTECTED_FIELD_MODIFICATION"
        # Ownership in DB must be unchanged
        assert matrix_db.expenses[exp.id].user_id == user_a.id


@pytest.mark.anyio
async def test_protected_field_privilege_escalation_via_patch_rejected(
    client: AsyncClient,
    headers_a: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    Sending privilege-escalation fields in a PATCH payload must be rejected
    with 400 PROTECTED_FIELD_MODIFICATION.
    """
    exp = Expense(
        id=uuid.uuid4(),
        user_id=user_a.id,
        category_id=DEFAULT_CAT_ID,
        amount_minor=10000,
        description="Privilege escalation test",
        expense_date=datetime.now(UTC).date(),
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        deleted_at=None,
    )
    matrix_db.expenses[exp.id] = exp

    escalation_payloads = [
        {"role": "admin", "version": 1},
        {"is_admin": True, "version": 1},
        {"isAdmin": True, "version": 1},
        {"is_superuser": True, "version": 1},
        {"group_role": "admin", "version": 1},
        {"permissions": ["admin"], "version": 1},
    ]
    for payload in escalation_payloads:
        res = await client.patch(
            f"/api/v1/expenses/{exp.id}", json=payload, headers=headers_a
        )
        assert res.status_code == 400, (
            f"Payload {payload} should be rejected with 400, got {res.status_code}"
        )
        assert res.json()["code"] == "PROTECTED_FIELD_MODIFICATION"


@pytest.mark.anyio
async def test_ownership_forgery_via_post_rejected(
    client: AsyncClient,
    headers_a: dict,
    user_b: User,
):
    """
    Supplying a foreign user_id in the expense creation body must be rejected
    with 400 PROTECTED_FIELD_MODIFICATION. No expense is created.
    """
    res = await client.post(
        "/api/v1/expenses",
        json={
            "user_id": str(user_b.id),
            "amount_minor": 20000,
            "description": "Forged ownership expense",
            "category_id": str(DEFAULT_CAT_ID),
        },
        headers=headers_a,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "PROTECTED_FIELD_MODIFICATION"


# ==============================================================================
# 7. Actor 3 — Authorized Owner: Full Lifecycle Verification
# ==============================================================================

@pytest.mark.anyio
async def test_owner_full_expense_lifecycle(
    client: AsyncClient,
    headers_a: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """
    Verifies that a legitimate owner can perform the full Create → Read →
    Update → Delete → Restore lifecycle without restriction.
    """
    # Create
    res_create = await client.post(
        "/api/v1/expenses",
        json={
            "amount_minor": 18000,
            "description": "Owner Dinner",
            "category_id": str(DEFAULT_CAT_ID),
        },
        headers=headers_a,
    )
    assert res_create.status_code == 201, f"Create failed: {res_create.text}"
    exp_id = res_create.json()["data"]["id"]
    assert res_create.json()["data"]["userId"] == str(user_a.id)

    # Read
    res_read = await client.get(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert res_read.status_code == 200
    assert res_read.json()["data"]["description"] == "Owner Dinner"

    # Update
    res_update = await client.patch(
        f"/api/v1/expenses/{exp_id}",
        json={"description": "Owner Dinner (updated)", "version": 1},
        headers=headers_a,
    )
    assert res_update.status_code == 200
    assert res_update.json()["data"]["version"] == 2

    # Soft delete
    res_del = await client.delete(f"/api/v1/expenses/{exp_id}", headers=headers_a)
    assert res_del.status_code == 200

    # Restore
    res_restore = await client.post(
        f"/api/v1/expenses/{exp_id}/restore", headers=headers_a
    )
    assert res_restore.status_code == 200
    assert res_restore.json()["data"]["deletedAt"] is None


@pytest.mark.anyio
async def test_owner_list_and_totals(
    client: AsyncClient,
    headers_a: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """Verifies that GET /expenses and GET /expenses/totals work for the owner."""
    exp = Expense(
        id=uuid.uuid4(), user_id=user_a.id, category_id=DEFAULT_CAT_ID,
        amount_minor=25000, description="Owner list test",
        expense_date=datetime.now(UTC).date(), version=1,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None,
    )
    matrix_db.expenses[exp.id] = exp

    res_list = await client.get("/api/v1/expenses", headers=headers_a)
    assert res_list.status_code == 200
    ids = [item["id"] for item in res_list.json()["data"]]
    assert str(exp.id) in ids

    res_totals = await client.get("/api/v1/expenses/totals", headers=headers_a)
    assert res_totals.status_code == 200
    assert res_totals.json()["data"]["totalPaise"] == 25000


@pytest.mark.anyio
async def test_owner_profile_and_sessions(
    client: AsyncClient,
    headers_a: dict,
    user_a: User,
    matrix_db: MatrixDB,
):
    """GET /auth/me and GET /auth/sessions work for the authenticated owner."""
    res_me = await client.get("/api/v1/auth/me", headers=headers_a)
    assert res_me.status_code == 200
    assert res_me.json()["email"] == user_a.email

    # Seed a token for user_a
    sess = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token("owner_raw_token"),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        is_revoked=False,
    )
    matrix_db.tokens[sess.id] = sess

    res_sessions = await client.get("/api/v1/auth/sessions", headers=headers_a)
    assert res_sessions.status_code == 200


# ==============================================================================
# 8. Group Authorization — unit-level (no HTTP endpoints yet)
# ==============================================================================

def test_group_policy_member_access(user_a, user_b):
    """
    GroupPolicy.authorize_member succeeds for a member and raises 403 for a
    non-member.  No group HTTP endpoints exist yet (future US-17 scope).
    """
    from app.core.authorization import GroupPolicy

    group_id = uuid.uuid4()
    members = {user_a.id}

    # Member succeeds silently
    GroupPolicy.authorize_member(user_a, group_id, members)

    # Non-member raises 403 GROUP_ACCESS_DENIED
    with pytest.raises(Exception) as exc_info:
        GroupPolicy.authorize_member(user_b, group_id, members)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "GROUP_ACCESS_DENIED"


def test_group_policy_admin_access(user_a, user_b):
    """
    GroupPolicy.authorize_admin:
    - Admin succeeds.
    - Member without admin role raises 403 INSUFFICIENT_PERMISSIONS.
    """
    from app.core.authorization import GroupPolicy

    group_id = uuid.uuid4()
    members = {user_a.id, user_b.id}
    admins = {user_a.id}

    # Admin succeeds
    GroupPolicy.authorize_admin(user_a, group_id, members, admins)

    # Member without admin raises 403
    with pytest.raises(Exception) as exc_info:
        GroupPolicy.authorize_admin(user_b, group_id, members, admins)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "INSUFFICIENT_PERMISSIONS"


# ==============================================================================
# 9. Safe Error Envelopes — No Sensitive Leakage
# ==============================================================================

@pytest.mark.anyio
async def test_error_responses_conform_to_envelope_and_leak_nothing(
    client: AsyncClient,
    headers_a: dict,
    user_a: User,
):
    """
    Every error response (4xx) must:
    1. Conform to the ApiErrorResponse schema: code, message, isRetryable.
    2. Never expose stack traces, SQL, internal identifiers, or passwords.
    """
    forbidden_terms = [
        "traceback",
        'file "',
        "select ",
        "insert ",
        "update ",
        "delete from",
        "sqlalchemy",
        "asyncpg",
        "psycopg",
        "password_hash",
        "hashed_password",
    ]

    error_scenarios = [
        ("GET",    f"/api/v1/expenses/{uuid.uuid4()}",     None,                   headers_a),
        ("PATCH",  f"/api/v1/expenses/{uuid.uuid4()}",     {"user_id": str(uuid.uuid4()), "version": 1}, headers_a),
        ("GET",    f"/api/v1/expenses?user_id={uuid.uuid4()}", None,              headers_a),
        ("GET",    "/api/v1/expenses",                     None,                   {}),         # no auth
        ("DELETE", f"/api/v1/auth/sessions/{uuid.uuid4()}", None,                 {}),         # no auth
    ]

    for method, path, body, hdrs in error_scenarios:
        res = await client.request(method, path, json=body, headers=hdrs)
        assert res.status_code in (400, 401, 403, 404), (
            f"{method} {path}: expected 4xx, got {res.status_code}"
        )
        data = res.json()
        assert "code" in data,        f"{method} {path}: 'code' missing from error envelope"
        assert "message" in data,     f"{method} {path}: 'message' missing from error envelope"
        assert "isRetryable" in data, f"{method} {path}: 'isRetryable' missing from error envelope"
        assert data["isRetryable"] is False

        raw = res.text.lower()
        for term in forbidden_terms:
            assert term.lower() not in raw, (
                f"Sensitive term '{term}' found in error response for "
                f"{method} {path}: {res.text[:400]}"
            )
