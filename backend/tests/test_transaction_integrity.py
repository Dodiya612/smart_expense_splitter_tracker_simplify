"""Transactions and failure handling (US-34 / T-38).

Fault-injection tests for every backend write path that writes more than one row
(or one row plus an idempotency record or audit event).

How the harness works
---------------------
Each test reuses the in-memory fake session of the module that already tests that
feature, wrapped in ``FaultInjectingSession``. The wrapper behaves like a real
PostgreSQL session for transactions:

* It snapshots the fake store's *committed* state after every successful commit.
* ``rollback()`` and ``close()`` restore that snapshot (uncommitted work is lost,
  exactly as when a transaction aborts or the connection drops).
* A fault can be armed: raise a dropped-connection ``OperationalError`` when a
  flush/commit would write a chosen row type (for example the audit event or the
  second insert), on any commit, or just *after* a commit succeeded (response lost).

If a write path committed part of its rows before the failure, that part survives
the restore and the "nothing changed" assertion fails. The real-database version of
this check is tests/test_transaction_integrity_pg.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.exc import NoInspectionAvailable, OperationalError

from app.ai.quota import AIQuotaService, log_ai_usage
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
)
from app.main import app
from app.models.ai_usage_log import AIUsageLog
from app.models.category import Category
from app.models.expense import AuditEvent, Expense, ExpenseShare
from app.models.group import (
    Group,
    GroupInvitation,
    GroupMember,
    GroupMemberRole,
    GroupMemberStatus,
    GroupType,
    InvitationStatus,
)
from app.models.idempotency import IdempotencyRecord
from app.models.rate_limit import LoginRateLimit
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import notifications
from tests import notification_fakes
from tests.test_ai_quota import QuotaFakeAsyncSession, QuotaFakeDB
from tests.test_authorization import FakeAuthAsyncSession, FakeAuthTestDB
from tests.test_groups import FakeGroupAsyncSession, FakeGroupDB
from tests.test_groups import FakeResult as FakeGroupResult
from tests.test_sessions import FakeAsyncSession as FakeAuthSession
from tests.test_sessions import FakeInMemoryDB as FakeAuthDB
from tests.test_settlements import FakeSettlementAsyncSession, FakeSettlementDB


# ==============================================================================
# Harness
# ==============================================================================


def dropped_connection() -> OperationalError:
    return OperationalError(
        "COMMIT", {}, ConnectionResetError("server closed the connection unexpectedly")
    )


def _column_values(obj: Any) -> dict[str, Any] | None:
    try:
        mapper = sa_inspect(obj).mapper
    except NoInspectionAvailable:
        return None
    return {attr.key: getattr(obj, attr.key) for attr in mapper.column_attrs}


def _containers(store: Any) -> list[tuple[str, Any]]:
    return [(n, c) for n, c in vars(store).items() if isinstance(c, (dict, list))]


def snapshot(store: Any) -> list[tuple[str, Any, list[tuple[Any, dict[str, Any]]]]]:
    snap = []
    for name, container in _containers(store):
        if isinstance(container, dict):
            items: Any = dict(container)
            objs = list(container.values())
        else:
            items = list(container)
            objs = list(container)
        states = [(o, vals) for o in objs if (vals := _column_values(o)) is not None]
        snap.append((name, items, states))
    return snap


def restore(store: Any, snap: list[tuple[str, Any, list[tuple[Any, dict[str, Any]]]]]) -> None:
    for name, items, states in snap:
        container = getattr(store, name)
        if isinstance(container, dict):
            container.clear()
            container.update(items)
        else:
            container[:] = items
        for obj, vals in states:
            for key, val in vals.items():
                setattr(obj, key, val)


def rows(store: Any) -> dict[str, list[str]]:
    """Comparable picture of every row in the fake store (all column values)."""
    out: dict[str, list[str]] = {}
    for name, container in _containers(store):
        objs = container.values() if isinstance(container, dict) else container
        out[name] = sorted(repr(sorted((_column_values(o) or {"obj": o}).items())) for o in objs)
    return out


class FaultInjectingSession:
    """Wraps a fake session and gives it PostgreSQL-like transaction semantics."""

    def __init__(self, inner: Any, store: Any) -> None:
        self.inner = inner
        self.store = store
        self.pending: list[Any] = []
        self.fail_types: tuple[type, ...] = ()
        self.fail_on_commit = False
        self.fail_after_commit = False
        self.commits = 0
        self.rollbacks = 0
        self._committed = snapshot(store)

    def arm(self, *, types: tuple[type, ...] = (), on_commit: bool = False, after_commit: bool = False) -> None:
        self.fail_types = types
        self.fail_on_commit = on_commit
        self.fail_after_commit = after_commit

    def disarm(self) -> None:
        self.arm()

    def mark_committed(self) -> None:
        """Treat the current store as committed (after test setup outside the API)."""
        self._committed = snapshot(self.store)

    def _check_pending(self) -> None:
        if self.fail_types and any(isinstance(o, self.fail_types) for o in self.pending):
            raise dropped_connection()

    def add(self, obj: Any) -> None:
        self.pending.append(obj)
        self.inner.add(obj)

    async def flush(self) -> None:
        self._check_pending()
        await self.inner.flush()

    async def commit(self) -> None:
        self._check_pending()
        if self.fail_on_commit:
            raise dropped_connection()
        await self.inner.commit()
        self.pending.clear()
        self.commits += 1
        self._committed = snapshot(self.store)
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise dropped_connection()

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.pending.clear()
        await self.inner.rollback()
        restore(self.store, self._committed)

    async def close(self) -> None:
        # Closing a session discards anything not committed.
        self.pending.clear()
        restore(self.store, self._committed)

    async def execute(self, stmt: Any, *args: Any, **kwargs: Any) -> Any:
        return await self.inner.execute(stmt, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


@asynccontextmanager
async def api(session: FaultInjectingSession) -> AsyncIterator[AsyncClient]:
    """App client whose get_db behaves like app.core.database.get_db."""

    async def override_get_db() -> AsyncIterator[FaultInjectingSession]:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def assert_retryable_error(resp: Any) -> None:
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["code"] == "INTERNAL_SERVER_ERROR"
    assert body["isRetryable"] is True
    assert body["message"]
    for leak in ("OperationalError", "Traceback", "server closed the connection"):
        assert leak not in resp.text


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, email=user.email)}"}


@pytest.fixture(autouse=True)
def _clean_notifications():
    notification_fakes.clear_emitted_notifications()
    yield
    notification_fakes.clear_emitted_notifications()


# ==============================================================================
# Worlds (fake stores with the rows each scenario needs)
# ==============================================================================

PASSWORD = "Password123!"


def auth_world() -> tuple[FaultInjectingSession, FakeAuthDB, User]:
    db = FakeAuthDB()
    user = User(
        id=uuid.uuid4(),
        email="riya@example.com",
        name="Riya",
        hashed_password=hash_password(PASSWORD),
        is_active=True,
    )
    db.users[user.id] = user
    return FaultInjectingSession(FakeAuthSession(db), db), db, user


def add_refresh_token(db: FakeAuthDB, user: User) -> tuple[str, RefreshToken]:
    raw = generate_refresh_token()
    now = datetime.now(UTC)
    tok = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token(raw),
        parent_id=None,
        is_revoked=False,
        expires_at=now + timedelta(days=1),
        remember=False,
        device_label="Pixel",
        last_seen=now,
        created_at=now,
    )
    db.tokens[tok.id] = tok
    return raw, tok


def expense_world() -> tuple[FaultInjectingSession, FakeAuthTestDB, User, Category]:
    db = FakeAuthTestDB()
    user = User(id=uuid.uuid4(), email="owner@example.com", name="Owner", hashed_password="x", is_active=True)
    cat = Category(id=uuid.uuid4(), name="Food & Dining", is_default=True)
    db.users[user.id] = user
    db.categories[cat.id] = cat
    return FaultInjectingSession(FakeAuthAsyncSession(db), db), db, user, cat


def add_personal_expense(db: FakeAuthTestDB, user: User, cat: Category, deleted: bool = False) -> Expense:
    now = datetime.now(UTC)
    exp = Expense(
        id=uuid.uuid4(), user_id=user.id, category_id=cat.id, amount_minor=2500,
        description="Lunch", expense_date=now.date(), version=1,
        created_at=now, updated_at=now, deleted_at=now if deleted else None,
    )
    db.expenses[exp.id] = exp
    return exp


class FakeGroupIdemDB(FakeGroupDB):
    """tests/test_groups.py fake store plus the idempotency_records table."""

    def __init__(self) -> None:
        super().__init__()
        self.idempotency_records: dict[tuple[uuid.UUID, str], IdempotencyRecord] = {}


class FakeGroupIdemSession(FakeGroupAsyncSession):
    def __init__(self, db: FakeGroupIdemDB) -> None:
        super().__init__(db)
        self.db: FakeGroupIdemDB = db

    async def commit(self) -> None:
        for obj in self.pending:
            if isinstance(obj, IdempotencyRecord):
                self.db.idempotency_records[(obj.user_id, obj.key)] = obj
        await super().commit()

    async def execute(self, stmt: Any) -> Any:
        sql = str(stmt).lower()
        if "from idempotency_records" in sql:
            await self.commit()
            params = stmt.compile().params
            uid = next((v for k, v in params.items() if "user_id" in k), None)
            key = next((v for k, v in params.items() if k.startswith("key")), None)
            if uid is None or key is None:
                return FakeGroupResult([])
            rec = self.db.idempotency_records.get((uid, key))
            return FakeGroupResult([rec] if rec else [])
        return await super().execute(stmt)


def group_world() -> tuple[FaultInjectingSession, FakeGroupIdemDB, User, User]:
    db = FakeGroupIdemDB()
    owner = User(id=uuid.uuid4(), email="owner@example.com", name="Owner", hashed_password="x", is_active=True)
    other = User(id=uuid.uuid4(), email="other@example.com", name="Other", hashed_password="x", is_active=True)
    db.users[owner.id] = owner
    db.users[other.id] = other
    return FaultInjectingSession(FakeGroupIdemSession(db), db), db, owner, other


async def create_group_via_api(client: AsyncClient, owner: User) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/groups", json={"name": "Flat 4B", "type": "flat"}, headers=bearer(owner)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def shared_world() -> tuple[FaultInjectingSession, FakeSettlementDB, list[User], Group, Category]:
    db = FakeSettlementDB()
    users = [
        User(id=uuid.uuid4(), email=f"{n}@example.com", name=n.title(), hashed_password="x", is_active=True)
        for n in ("alex", "blair", "casey")
    ]
    for u in users:
        db.users[u.id] = u
    cat = Category(id=uuid.uuid4(), name="Groceries", is_default=True)
    db.categories[cat.id] = cat
    now = datetime.now(UTC)
    grp = Group(id=uuid.uuid4(), name="Flat Expenses", type=GroupType.FLAT.value,
                created_by=users[0].id, created_at=now, updated_at=now)
    db.groups[grp.id] = grp
    members = []
    for i, u in enumerate(users):
        m = GroupMember(
            group_id=grp.id, user_id=u.id,
            role=GroupMemberRole.ADMIN.value if i == 0 else GroupMemberRole.MEMBER.value,
            status=GroupMemberStatus.ACTIVE.value,
            joined_at=now + timedelta(seconds=i), updated_at=now,
        )
        m.user = u
        db.group_members[(grp.id, u.id)] = m
        members.append(m)
    grp.members = members
    grp.creator = users[0]
    return FaultInjectingSession(FakeSettlementAsyncSession(db), db), db, users, grp, cat


async def add_shared_expense(client: AsyncClient, session: FaultInjectingSession, db: FakeSettlementDB,
                             grp: Group, cat: Category, payer: User) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/groups/{grp.id}/expenses",
        json={"amount_paise": 300000, "description": "Groceries", "category_id": str(cat.id), "split_mode": "equal"},
        headers=bearer(payer),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # The database fills version=1 on insert (server default); the fake does not.
    db.expenses[uuid.UUID(body["id"])].version = 1
    session.mark_committed()
    return body


# ==============================================================================
# 1. Auth: register, login, refresh, logout, revoke session
# ==============================================================================


@pytest.mark.asyncio
async def test_register_failure_after_user_insert_leaves_no_user_or_token():
    session, db, _ = auth_world()
    before = rows(db)
    session.arm(types=(RefreshToken,))  # user row flushed, then the token insert fails
    async with api(session) as client:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={"name": "New User", "email": "new@example.com", "password": PASSWORD},
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert not any(u.email == "new@example.com" for u in db.users.values())
    assert db.tokens == {}


@pytest.mark.asyncio
async def test_login_failure_keeps_failed_attempt_counter_and_creates_no_session():
    session, db, user = auth_world()
    db.rate_limits[user.email] = LoginRateLimit(
        id=uuid.uuid4(), key=user.email, attempts=2,
        last_attempt_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    session.mark_committed()
    before = rows(db)
    session.arm(types=(RefreshToken,))
    async with api(session) as client:
        resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.rate_limits[user.email].attempts == 2
    assert db.tokens == {}


@pytest.mark.asyncio
async def test_login_failure_after_expired_lockout_window_writes_nothing():
    session, db, user = auth_world()
    db.rate_limits[user.email] = LoginRateLimit(
        id=uuid.uuid4(), key=user.email, attempts=5,
        last_attempt_at=datetime.now(UTC) - timedelta(hours=2),
    )
    session.mark_committed()
    before = rows(db)
    session.arm(types=(RefreshToken,))
    async with api(session) as client:
        resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.rate_limits[user.email].attempts == 5


@pytest.mark.asyncio
async def test_login_success_still_clears_counter_and_creates_session():
    """Regression guard for the login fix: the happy path is unchanged."""
    session, db, user = auth_world()
    db.rate_limits[user.email] = LoginRateLimit(
        id=uuid.uuid4(), key=user.email, attempts=2,
        last_attempt_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    session.mark_committed()
    async with api(session) as client:
        resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    assert user.email not in db.rate_limits
    assert len(db.tokens) == 1
    assert session.commits == 1


@pytest.mark.asyncio
async def test_refresh_failure_keeps_parent_token_valid_and_adds_no_child():
    session, db, user = auth_world()
    raw, parent = add_refresh_token(db, user)
    session.mark_committed()
    before = rows(db)
    session.arm(types=(RefreshToken,))  # parent revoked in memory, child insert fails
    async with api(session) as client:
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw})
    assert_retryable_error(resp)
    assert rows(db) == before
    assert parent.is_revoked is False
    assert list(db.tokens) == [parent.id]


@pytest.mark.asyncio
async def test_logout_failure_revokes_nothing():
    session, db, user = auth_world()
    raw, tok = add_refresh_token(db, user)
    session.mark_committed()
    before = rows(db)
    session.arm(on_commit=True)
    async with api(session) as client:
        resp = await client.post("/api/v1/auth/logout", json={"refresh_token": raw}, headers=bearer(user))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert tok.is_revoked is False


@pytest.mark.asyncio
async def test_revoke_session_failure_revokes_nothing():
    session, db, user = auth_world()
    _, tok = add_refresh_token(db, user)
    session.mark_committed()
    before = rows(db)
    session.arm(on_commit=True)
    async with api(session) as client:
        resp = await client.delete(f"/api/v1/auth/sessions/{tok.family_id}", headers=bearer(user))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert tok.is_revoked is False


# ==============================================================================
# 2. Personal expenses (create with idempotency key, update, delete, restore)
# ==============================================================================


def personal_body(cat: Category) -> dict[str, Any]:
    return {"amount_minor": 2500, "description": "Lunch", "category_id": str(cat.id)}


@pytest.mark.asyncio
async def test_personal_expense_create_failure_leaves_no_expense_or_idempotency_record():
    session, db, user, cat = expense_world()
    before = rows(db)
    session.arm(types=(IdempotencyRecord,))
    async with api(session) as client:
        resp = await client.post(
            "/api/v1/expenses", json=personal_body(cat),
            headers={**bearer(user), "Idempotency-Key": "key-1"},
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.expenses == {}
    assert db.idempotency_records == {}


@pytest.mark.asyncio
async def test_personal_expense_retry_after_connection_drop_before_commit_creates_one():
    session, db, user, cat = expense_world()
    headers = {**bearer(user), "Idempotency-Key": "key-retry-1"}
    async with api(session) as client:
        session.arm(on_commit=True)
        first = await client.post("/api/v1/expenses", json=personal_body(cat), headers=headers)
        assert_retryable_error(first)
        assert db.expenses == {}
        session.disarm()
        retry = await client.post("/api/v1/expenses", json=personal_body(cat), headers=headers)
    assert retry.status_code == 201, retry.text
    assert len(db.expenses) == 1
    assert len(db.idempotency_records) == 1


@pytest.mark.asyncio
async def test_personal_expense_retry_after_connection_drop_after_commit_creates_one():
    """Commit succeeded but the response was lost: the retry replays, no duplicate."""
    session, db, user, cat = expense_world()
    headers = {**bearer(user), "Idempotency-Key": "key-retry-2"}
    async with api(session) as client:
        session.arm(after_commit=True)
        first = await client.post("/api/v1/expenses", json=personal_body(cat), headers=headers)
        assert_retryable_error(first)
        assert len(db.expenses) == 1  # it was saved
        retry = await client.post("/api/v1/expenses", json=personal_body(cat), headers=headers)
    assert retry.status_code == 201, retry.text
    assert retry.headers.get("x-idempotent-replay") == "true"
    assert len(db.expenses) == 1
    assert retry.json()["data"]["id"] == str(next(iter(db.expenses)))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["update", "delete", "restore"])
async def test_personal_expense_single_row_writes_roll_back(operation):
    session, db, user, cat = expense_world()
    exp = add_personal_expense(db, user, cat, deleted=(operation == "restore"))
    session.mark_committed()
    before = rows(db)
    session.arm(on_commit=True)
    async with api(session) as client:
        if operation == "update":
            resp = await client.patch(
                f"/api/v1/expenses/{exp.id}", json={"description": "Dinner", "version": 1}, headers=bearer(user)
            )
        elif operation == "delete":
            resp = await client.delete(f"/api/v1/expenses/{exp.id}", headers=bearer(user))
        else:
            resp = await client.post(f"/api/v1/expenses/{exp.id}/restore", headers=bearer(user))
    assert_retryable_error(resp)
    assert rows(db) == before


@pytest.mark.asyncio
async def test_category_feedback_failure_writes_nothing():
    session, db, user, cat = expense_world()
    before = rows(db)
    session.arm(on_commit=True)
    async with api(session) as client:
        resp = await client.post(
            "/api/v1/ai/category-suggestion/feedback",
            json={
                "description": "Swiggy order",
                "suggestedCategoryId": str(cat.id),
                "chosenCategoryId": str(cat.id),
                "accepted": True,
            },
            headers=bearer(user),
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.feedback == []


# ==============================================================================
# 3. Groups: create, join by code, join code generate/revoke, invitations, remove
# ==============================================================================


@pytest.mark.asyncio
async def test_group_create_failure_leaves_no_group_member_or_join_code():
    session, db, owner, _ = group_world()
    before = rows(db)
    session.arm(types=(GroupInvitation,))  # group flushed, member added, join code insert fails
    async with api(session) as client:
        resp = await client.post("/api/v1/groups", json={"name": "Flat 4B", "type": "flat"}, headers=bearer(owner))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.groups == {}
    assert db.group_members == {}
    assert db.invitations == {}


@pytest.mark.asyncio
async def test_join_by_code_failure_adds_no_member():
    session, db, owner, other = group_world()
    async with api(session) as client:
        grp = await create_group_via_api(client, owner)
        before = rows(db)
        session.arm(on_commit=True)
        resp = await client.post("/api/v1/groups/join", json={"code": grp["joinCode"]}, headers=bearer(other))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert (uuid.UUID(grp["id"]), other.id) not in db.group_members


@pytest.mark.asyncio
async def test_join_code_rotation_failure_keeps_old_code_active():
    session, db, owner, _ = group_world()
    async with api(session) as client:
        grp = await create_group_via_api(client, owner)
        before = rows(db)
        session.arm(types=(GroupInvitation,))  # old code revoked in memory, new code insert fails
        resp = await client.post(f"/api/v1/groups/{grp['id']}/join-code", headers=bearer(owner))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert [i.status for i in db.invitations.values()] == [InvitationStatus.PENDING.value]


@pytest.mark.asyncio
async def test_join_code_revoke_failure_keeps_code_active():
    session, db, owner, _ = group_world()
    async with api(session) as client:
        grp = await create_group_via_api(client, owner)
        before = rows(db)
        session.arm(on_commit=True)
        resp = await client.delete(f"/api/v1/groups/{grp['id']}/join-code", headers=bearer(owner))
    assert_retryable_error(resp)
    assert rows(db) == before


@pytest.mark.asyncio
async def test_invitation_create_failure_writes_nothing():
    session, db, owner, other = group_world()
    async with api(session) as client:
        grp = await create_group_via_api(client, owner)
        before = rows(db)
        session.arm(on_commit=True)
        resp = await client.post(
            f"/api/v1/groups/{grp['id']}/invitations", json={"email": other.email}, headers=bearer(owner)
        )
    assert_retryable_error(resp)
    assert rows(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["accept", "decline"])
async def test_invitation_accept_or_decline_failure_changes_nothing(action):
    session, db, owner, other = group_world()
    async with api(session) as client:
        grp = await create_group_via_api(client, owner)
        inv = await client.post(
            f"/api/v1/groups/{grp['id']}/invitations", json={"email": other.email}, headers=bearer(owner)
        )
        assert inv.status_code == 201, inv.text
        before = rows(db)
        session.arm(on_commit=True)  # accept = new member row + invitation status together
        resp = await client.post(f"/api/v1/invitations/{inv.json()['id']}/{action}", headers=bearer(other))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert (uuid.UUID(grp["id"]), other.id) not in db.group_members


@pytest.mark.asyncio
async def test_remove_member_failure_keeps_member_active():
    session, db, owner, other = group_world()
    async with api(session) as client:
        grp = await create_group_via_api(client, owner)
        joined = await client.post("/api/v1/groups/join", json={"code": grp["joinCode"]}, headers=bearer(other))
        assert joined.status_code == 200, joined.text
        before = rows(db)
        session.arm(on_commit=True)
        resp = await client.delete(f"/api/v1/groups/{grp['id']}/members/{other.id}", headers=bearer(owner))
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.group_members[(uuid.UUID(grp["id"]), other.id)].status == GroupMemberStatus.ACTIVE.value


# ==============================================================================
# 4. Shared expenses (create, edit, delete) and settlements
# ==============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", [ExpenseShare, AuditEvent])
async def test_shared_expense_create_failure_leaves_nothing(fail_on):
    session, db, users, grp, cat = shared_world()
    before = rows(db)
    session.arm(types=(fail_on,))
    async with api(session) as client:
        resp = await client.post(
            f"/api/v1/groups/{grp.id}/expenses",
            json={"amount_paise": 300000, "description": "Groceries", "category_id": str(cat.id)},
            headers=bearer(users[0]),
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.expenses == {}
    assert db.expense_payments == {}
    assert db.expense_shares == {}
    assert db.audit_events == {}
    assert notification_fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_shared_expense_edit_failure_keeps_original_amount_payments_and_shares():
    session, db, users, grp, cat = shared_world()
    async with api(session) as client:
        exp = await add_shared_expense(client, session, db, grp, cat, users[0])
        notification_fakes.clear_emitted_notifications()
        before = rows(db)
        session.arm(types=(AuditEvent,))  # expense updated, shares rewritten, audit insert fails
        resp = await client.patch(
            f"/api/v1/groups/{grp.id}/expenses/{exp['id']}",
            json={"amount_paise": 600000, "version": 1},
            headers=bearer(users[0]),
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    stored = db.expenses[uuid.UUID(exp["id"])]
    assert stored.amount_minor == 300000
    assert stored.version == 1
    assert sorted(s.amount_paise for s in db.expense_shares.values()) == [100000] * 3
    assert notification_fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_shared_expense_delete_failure_keeps_expense():
    session, db, users, grp, cat = shared_world()
    async with api(session) as client:
        exp = await add_shared_expense(client, session, db, grp, cat, users[0])
        notification_fakes.clear_emitted_notifications()
        before = rows(db)
        session.arm(types=(AuditEvent,))
        resp = await client.delete(
            f"/api/v1/groups/{grp.id}/expenses/{exp['id']}?version=1", headers=bearer(users[0])
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.expenses[uuid.UUID(exp["id"])].deleted_at is None
    assert notification_fakes.get_emitted_notifications() == []


def settlement_body(payer: User, payee: User) -> dict[str, Any]:
    return {"payer_id": str(payer.id), "payee_id": str(payee.id), "amount_paise": 100000}


@pytest.mark.asyncio
async def test_settlement_create_failure_leaves_no_settlement_audit_or_idempotency_record():
    session, db, users, grp, cat = shared_world()
    alex, blair, _ = users
    async with api(session) as client:
        await add_shared_expense(client, session, db, grp, cat, alex)
        before = rows(db)
        session.arm(types=(AuditEvent,))
        resp = await client.post(
            f"/api/v1/groups/{grp.id}/settlements", json=settlement_body(blair, alex),
            headers={**bearer(blair), "Idempotency-Key": "stl-1"},
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.settlements == {}
    assert db.idempotency_records == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("drop", ["before_commit", "after_commit"])
async def test_settlement_retry_after_dropped_connection_creates_one(drop):
    session, db, users, grp, cat = shared_world()
    alex, blair, _ = users
    headers = {**bearer(blair), "Idempotency-Key": f"stl-retry-{drop}"}
    async with api(session) as client:
        await add_shared_expense(client, session, db, grp, cat, alex)
        session.arm(on_commit=(drop == "before_commit"), after_commit=(drop == "after_commit"))
        first = await client.post(f"/api/v1/groups/{grp.id}/settlements", json=settlement_body(blair, alex), headers=headers)
        assert_retryable_error(first)
        session.disarm()
        retry = await client.post(f"/api/v1/groups/{grp.id}/settlements", json=settlement_body(blair, alex), headers=headers)
    assert retry.status_code == 201, retry.text
    assert len(db.settlements) == 1
    assert len([a for a in db.audit_events.values() if a.entity_type == "settlement"]) == 1
    assert retry.json()["id"] == str(next(iter(db.settlements)))
    if drop == "after_commit":
        assert retry.headers.get("x-idempotent-replay") == "true"


# ==============================================================================
# 4b. Idempotency-Key on group create and shared expense create (round 2)
# ==============================================================================

GROUP_BODY = {"name": "Flat 4B", "type": "flat"}


def shared_body(cat: Category, amount: int = 300000) -> dict[str, Any]:
    return {"amount_paise": amount, "description": "Groceries", "category_id": str(cat.id), "split_mode": "equal"}


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", [GroupInvitation, IdempotencyRecord])
async def test_group_create_with_key_failure_leaves_no_group_or_idempotency_record(fail_on):
    session, db, owner, _ = group_world()
    before = rows(db)
    session.arm(types=(fail_on,))
    async with api(session) as client:
        resp = await client.post(
            "/api/v1/groups", json=GROUP_BODY, headers={**bearer(owner), "Idempotency-Key": "grp-1"}
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.groups == {}
    assert db.group_members == {}
    assert db.invitations == {}
    assert db.idempotency_records == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("drop", ["before_commit", "after_commit"])
async def test_group_create_retry_after_dropped_connection_creates_one(drop):
    session, db, owner, _ = group_world()
    headers = {**bearer(owner), "Idempotency-Key": f"grp-retry-{drop}"}
    async with api(session) as client:
        session.arm(on_commit=(drop == "before_commit"), after_commit=(drop == "after_commit"))
        first = await client.post("/api/v1/groups", json=GROUP_BODY, headers=headers)
        assert_retryable_error(first)
        session.disarm()
        retry = await client.post("/api/v1/groups", json=GROUP_BODY, headers=headers)
    assert retry.status_code == 201, retry.text
    assert len(db.groups) == 1
    assert len(db.group_members) == 1
    assert len(db.invitations) == 1
    assert len(db.idempotency_records) == 1
    body = retry.json()
    assert body["id"] == str(next(iter(db.groups)))
    assert body["currentUserRole"] == "admin"
    assert [m["userId"] for m in body["members"]] == [str(owner.id)]
    if drop == "after_commit":
        assert retry.headers.get("x-idempotent-replay") == "true"
        # Join codes are stored only as hashes, so a replay never repeats the plaintext code.
        assert body["joinCode"] is None
    else:
        assert "x-idempotent-replay" not in retry.headers
        assert body["joinCode"]


@pytest.mark.asyncio
async def test_group_create_replay_and_conflict():
    session, db, owner, _ = group_world()
    headers = {**bearer(owner), "Idempotency-Key": "grp-same"}
    async with api(session) as client:
        first = await client.post("/api/v1/groups", json=GROUP_BODY, headers=headers)
        replay = await client.post("/api/v1/groups", json=GROUP_BODY, headers=headers)
        conflict = await client.post(
            "/api/v1/groups", json={"name": "Another flat", "type": "flat"}, headers=headers
        )
    assert first.status_code == 201
    assert "x-idempotent-replay" not in first.headers
    assert replay.status_code == 201
    assert replay.headers.get("x-idempotent-replay") == "true"
    expected = {**first.json(), "joinCode": None}
    assert replay.json() == expected
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(db.groups) == 1
    assert len(db.idempotency_records) == 1


@pytest.mark.asyncio
async def test_group_create_without_key_is_unchanged():
    session, db, owner, _ = group_world()
    async with api(session) as client:
        a = await client.post("/api/v1/groups", json=GROUP_BODY, headers=bearer(owner))
        b = await client.post("/api/v1/groups", json=GROUP_BODY, headers=bearer(owner))
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["joinCode"]
    assert "x-idempotent-replay" not in b.headers
    assert len(db.groups) == 2  # no key: two requests, two groups, exactly as before
    assert db.idempotency_records == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", [AuditEvent, IdempotencyRecord])
async def test_shared_expense_create_with_key_failure_leaves_nothing(fail_on):
    session, db, users, grp, cat = shared_world()
    before = rows(db)
    session.arm(types=(fail_on,))
    async with api(session) as client:
        resp = await client.post(
            f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat),
            headers={**bearer(users[0]), "Idempotency-Key": "exp-1"},
        )
    assert_retryable_error(resp)
    assert rows(db) == before
    assert db.expenses == {}
    assert db.expense_payments == {}
    assert db.expense_shares == {}
    assert db.audit_events == {}
    assert db.idempotency_records == {}
    assert notification_fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("drop", ["before_commit", "after_commit"])
async def test_shared_expense_retry_after_dropped_connection_creates_one(drop):
    session, db, users, grp, cat = shared_world()
    headers = {**bearer(users[0]), "Idempotency-Key": f"exp-retry-{drop}"}
    async with api(session) as client:
        session.arm(on_commit=(drop == "before_commit"), after_commit=(drop == "after_commit"))
        first = await client.post(f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat), headers=headers)
        assert_retryable_error(first)
        session.disarm()
        retry = await client.post(f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat), headers=headers)
    assert retry.status_code == 201, retry.text
    assert len(db.expenses) == 1
    assert len(db.expense_payments) == 1
    assert len(db.expense_shares) == 3
    assert len([a for a in db.audit_events.values() if a.action == "expense_created"]) == 1
    assert len(db.idempotency_records) == 1
    body = retry.json()
    assert body["id"] == str(next(iter(db.expenses)))
    assert sorted(s["amountPaise"] for s in body["shares"]) == [100000] * 3
    if drop == "after_commit":
        assert retry.headers.get("x-idempotent-replay") == "true"
    # The other two members (not the actor) are notified once, for the one expense that exists.
    assert len(notification_fakes.get_emitted_notifications()) == 2


@pytest.mark.asyncio
async def test_shared_expense_replay_and_conflict():
    session, db, users, grp, cat = shared_world()
    headers = {**bearer(users[0]), "Idempotency-Key": "exp-same"}
    async with api(session) as client:
        first = await client.post(f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat), headers=headers)
        replay = await client.post(f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat), headers=headers)
        conflict = await client.post(
            f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat, amount=450000), headers=headers
        )
    assert first.status_code == 201
    assert "x-idempotent-replay" not in first.headers
    assert replay.status_code == 201
    assert replay.headers.get("x-idempotent-replay") == "true"
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(db.expenses) == 1
    assert len(notification_fakes.get_emitted_notifications()) == 2  # the replay notified no one again


@pytest.mark.asyncio
async def test_shared_expense_create_without_key_is_unchanged():
    session, db, users, grp, cat = shared_world()
    async with api(session) as client:
        a = await client.post(f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat), headers=bearer(users[0]))
        b = await client.post(f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat), headers=bearer(users[0]))
    assert a.status_code == 201
    assert b.status_code == 201
    assert "x-idempotent-replay" not in b.headers
    assert len(db.expenses) == 2
    assert db.idempotency_records == {}


@pytest.mark.asyncio
async def test_blank_idempotency_key_is_rejected():
    session, db, users, grp, cat = shared_world()
    async with api(session) as client:
        resp = await client.post(
            f"/api/v1/groups/{grp.id}/expenses", json=shared_body(cat),
            headers={**bearer(users[0]), "Idempotency-Key": "   "},
        )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert db.expenses == {}


# ==============================================================================
# 5. Notifications run only after commit and can never undo a saved record
# ==============================================================================


@pytest.mark.asyncio
async def test_failing_notification_does_not_turn_a_saved_expense_into_an_error(monkeypatch):
    session, db, users, grp, cat = shared_world()

    async def broken_persist(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("notification backend down")

    monkeypatch.setattr(notifications, "_persist", broken_persist)
    async with api(session) as client:
        resp = await client.post(
            f"/api/v1/groups/{grp.id}/expenses",
            json={"amount_paise": 300000, "description": "Groceries", "category_id": str(cat.id)},
            headers=bearer(users[0]),
        )
    assert resp.status_code == 201, resp.text
    assert len(db.expenses) == 1
    assert len(db.expense_shares) == 3


# ==============================================================================
# 6. AI quota bookkeeping: a failed write rolls the shared session back
# ==============================================================================


class PoisonedAfterFailureSession(QuotaFakeAsyncSession):
    """Like a real AsyncSession: after a failed commit, every query raises until rollback()."""

    def __init__(self, db: QuotaFakeDB) -> None:
        super().__init__(db, fail_commits=True)
        self.needs_rollback = False

    async def commit(self) -> None:
        try:
            await super().commit()
        except OperationalError:
            self.needs_rollback = True
            raise

    async def rollback(self) -> None:
        self.needs_rollback = False
        await super().rollback()

    async def execute(self, stmt: Any) -> Any:
        if self.needs_rollback:
            raise OperationalError(
                "Can't reconnect until invalid transaction is rolled back", {}, RuntimeError("aborted")
            )
        return await super().execute(stmt)


async def session_still_usable(sess: PoisonedAfterFailureSession) -> bool:
    try:
        await sess.execute(select(AIUsageLog).where(AIUsageLog.id == uuid.uuid4()))
        return True
    except OperationalError:
        return False


@pytest.mark.asyncio
async def test_ai_usage_log_failure_rolls_back_the_request_session():
    sess = PoisonedAfterFailureSession(QuotaFakeDB())
    result = await log_ai_usage(
        user_id=uuid.uuid4(), feature="categorize", provider="groq", model="m",
        status="quota_exceeded", db=sess,  # type: ignore[arg-type]
    )
    assert result is None
    assert sess.db.ai_logs == []
    assert await session_still_usable(sess)


@pytest.mark.asyncio
async def test_ai_reservation_failure_rolls_back_so_the_request_can_fall_back(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_ENABLED", True)
    sess = PoisonedAfterFailureSession(QuotaFakeDB())
    qs = AIQuotaService()
    async with qs.reserve(user_id=uuid.uuid4(), feature="categorize", db=sess, raise_on_exceeded=False) as res:  # type: ignore[arg-type]
        assert res.allowed  # the pending row failed to save, but the feature still answers
        assert await session_still_usable(sess)
        await res.finalize(status="success", db=sess)  # type: ignore[arg-type]
        assert await session_still_usable(sess)
    assert sess.db.ai_logs == []
    assert await session_still_usable(sess)
