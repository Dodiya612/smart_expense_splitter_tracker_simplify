import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, hash_refresh_token
from app.main import app
from app.models.rate_limit import LoginRateLimit
from app.models.refresh_token import RefreshToken
from app.models.user import User


class FakeInMemoryDB:
    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.tokens: dict[uuid.UUID, RefreshToken] = {}
        self.rate_limits: dict[str, LoginRateLimit] = {}

    def add_user(self, user: User) -> User:
        if user.id is None:
            user.id = uuid.uuid4()
        self.users[user.id] = user
        return user


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar_one(self):
        if not self._items:
            raise Exception("No row found")
        return self._items[0]

    def scalar(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return FakeScalars(self._items)


class FakeAsyncSession:
    def __init__(self, db: FakeInMemoryDB):
        self.db = db
        self.pending_users: dict[uuid.UUID, User] = {}
        self.pending_tokens: dict[uuid.UUID, RefreshToken] = {}
        self.pending_rate_limits: dict[str, LoginRateLimit] = {}

    def add(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, RefreshToken):
            now_utc = datetime.now(timezone.utc)
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now_utc
            if getattr(obj, "last_seen", None) is None:
                obj.last_seen = now_utc
            self.pending_tokens[obj.id] = obj
        elif isinstance(obj, User):
            self.pending_users[obj.id] = obj
        elif isinstance(obj, LoginRateLimit):
            self.pending_rate_limits[obj.key] = obj

    async def delete(self, obj):
        if isinstance(obj, LoginRateLimit):
            self.db.rate_limits.pop(obj.key, None)
            self.pending_rate_limits.pop(obj.key, None)

    async def flush(self):
        self.db.users.update(self.pending_users)
        self.db.tokens.update(self.pending_tokens)
        self.db.rate_limits.update(self.pending_rate_limits)
        self.pending_users.clear()
        self.pending_tokens.clear()
        self.pending_rate_limits.clear()

    async def commit(self):
        await self.flush()

    async def rollback(self):
        self.pending_users.clear()
        self.pending_tokens.clear()
        self.pending_rate_limits.clear()

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        await self.flush()
        params = stmt.compile().params
        sql_str = str(stmt).lower()

        # 1. SELECT User queries
        if "from users" in sql_str:
            email_val = next((v for k, v in params.items() if "email" in k), None)
            if email_val is not None:
                matched = [u for u in self.db.users.values() if u.email.lower() == str(email_val).lower()]
                return FakeResult(matched)
            id_val = next((v for k, v in params.items() if "id" in k), None)
            if id_val is not None:
                matched = [u for u in self.db.users.values() if str(u.id) == str(id_val)]
                return FakeResult(matched)
            return FakeResult(list(self.db.users.values()))

        # 2. SELECT RefreshToken queries
        if "from refresh_tokens" in sql_str:
            hash_val = next((v for k, v in params.items() if "hash" in k), None)
            if hash_val is not None:
                matched = [t for t in self.db.tokens.values() if t.token_hash == hash_val]
                return FakeResult(matched)

            user_val = next((v for k, v in params.items() if "user_id" in k or "user_1" in k), None)
            if user_val is not None and "is_revoked" in sql_str:
                now_utc = datetime.now(timezone.utc)
                matched = [
                    t for t in self.db.tokens.values()
                    if str(t.user_id) == str(user_val) and not t.is_revoked and t.expires_at > now_utc
                ]
                matched.sort(key=lambda t: getattr(t, "last_seen", t.created_at), reverse=True)
                return FakeResult(matched)

            fam_or_id = next((v for k, v in params.items() if (isinstance(v, uuid.UUID) or "family" in k or "id" in k) and "user" not in k and "hash" not in k), None)
            if fam_or_id is not None:
                matched = [t for t in self.db.tokens.values() if str(t.family_id) == str(fam_or_id) or str(t.id) == str(fam_or_id)]
                return FakeResult(matched)

            return FakeResult(list(self.db.tokens.values()))

        # 3. UPDATE RefreshToken queries
        if "update refresh_tokens" in sql_str:
            fam_val = next((v for k, v in params.items() if "family" in k), None)
            user_val = next((v for k, v in params.items() if "user_id" in k or "user_1" in k), None)
            if fam_val is not None:
                for t in self.db.tokens.values():
                    if str(t.family_id) == str(fam_val):
                        if user_val is None or str(t.user_id) == str(user_val):
                            t.is_revoked = True
            elif user_val is not None:
                for t in self.db.tokens.values():
                    if str(t.user_id) == str(user_val):
                        t.is_revoked = True
            return FakeResult([])

        # 4. SELECT LoginRateLimit queries
        if "from login_rate_limits" in sql_str:
            key_val = next((v for k, v in params.items() if "key" in k), None)
            if key_val is not None:
                matched = [r for r in self.db.rate_limits.values() if r.key == key_val]
                return FakeResult(matched)
            return FakeResult(list(self.db.rate_limits.values()))

        return FakeResult([])


@pytest.fixture
def fake_db():
    return FakeInMemoryDB()


@pytest.fixture
async def session_client(fake_db):
    async def override_get_db():
        yield FakeAsyncSession(fake_db)

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_remember_me_enabled_30_day_expiry(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that remember_me=True yields a 30-day token expiration."""
    user = User(
        id=uuid.uuid4(),
        email="remember_true@example.com",
        name="Remember True",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    response = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "remember_true@example.com",
            "password": "Password123!",
            "remember_me": True,
            "device_label": "Chrome on macOS",
        },
    )
    assert response.status_code == 200
    assert len(fake_db.tokens) == 1
    token = list(fake_db.tokens.values())[0]
    assert token.remember is True
    assert token.device_label == "Chrome on macOS"

    now = datetime.now(timezone.utc)
    # Expiry should be approx 30 days away (within 1 minute delta)
    expected_expiry = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    delta = abs((token.expires_at - expected_expiry).total_seconds())
    assert delta < 60


@pytest.mark.anyio
async def test_remember_me_disabled_or_omitted_24_hour_expiry(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that remember_me=False or omitted yields a 24-hour token expiration."""
    user = User(
        id=uuid.uuid4(),
        email="remember_false@example.com",
        name="Remember False",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # 1. Omitted remember_me
    response = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "remember_false@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 200
    token = list(fake_db.tokens.values())[0]
    assert token.remember is False

    now = datetime.now(timezone.utc)
    expected_expiry = now + timedelta(hours=settings.REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER)
    delta = abs((token.expires_at - expected_expiry).total_seconds())
    assert delta < 60

    # 2. Explicit remember_me=False
    fake_db.tokens.clear()
    response2 = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "remember_false@example.com",
            "password": "Password123!",
            "remember_me": False,
        },
    )
    assert response2.status_code == 200
    token2 = list(fake_db.tokens.values())[0]
    assert token2.remember is False
    delta2 = abs((token2.expires_at - expected_expiry).total_seconds())
    assert delta2 < 60


@pytest.mark.anyio
async def test_rotation_preserves_policy_and_device_metadata(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that refresh token rotation propagates remember_me policy, device_label, and updates last_seen."""
    user = User(
        id=uuid.uuid4(),
        email="rotate_policy@example.com",
        name="Rotate Policy",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    login_res = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "rotate_policy@example.com",
            "password": "Password123!",
            "remember_me": True,
            "device_label": "iPhone 15 - iOS App",
        },
    )
    assert login_res.status_code == 200
    raw_refresh_token = login_res.json()["tokens"]["refreshToken"]

    # Initial token in DB
    initial_tokens = list(fake_db.tokens.values())
    assert len(initial_tokens) == 1
    t1 = initial_tokens[0]
    assert t1.remember is True
    assert t1.device_label == "iPhone 15 - iOS App"
    initial_last_seen = t1.last_seen

    # Rotate token
    refresh_res = await session_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": raw_refresh_token},
    )
    assert refresh_res.status_code == 200

    # Now we should have 2 tokens in DB: t1 revoked, t2 active
    assert len(fake_db.tokens) == 2
    assert t1.is_revoked is True
    assert t1.last_seen >= initial_last_seen

    t2 = next(t for t in fake_db.tokens.values() if not t.is_revoked)
    assert t2.family_id == t1.family_id
    assert t2.remember is True
    assert t2.device_label == "iPhone 15 - iOS App"
    # Child token inherits 30-day expiry
    now = datetime.now(timezone.utc)
    expected_expiry = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    assert abs((t2.expires_at - expected_expiry).total_seconds()) < 60


@pytest.mark.anyio
async def test_rotation_preserves_24_hour_expiry_when_remember_false(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that rotation preserves 24h expiry when remember was false."""
    user = User(
        id=uuid.uuid4(),
        email="rotate_24h@example.com",
        name="Rotate 24h",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    login_res = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "rotate_24h@example.com",
            "password": "Password123!",
            "remember_me": False,
        },
    )
    assert login_res.status_code == 200
    raw_refresh = login_res.json()["tokens"]["refreshToken"]

    refresh_res = await session_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": raw_refresh},
    )
    assert refresh_res.status_code == 200

    t2 = next(t for t in fake_db.tokens.values() if not t.is_revoked)
    assert t2.remember is False
    now = datetime.now(timezone.utc)
    expected_expiry = now + timedelta(hours=settings.REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER)
    assert abs((t2.expires_at - expected_expiry).total_seconds()) < 60


@pytest.mark.anyio
async def test_list_active_sessions_for_authenticated_user(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that GET /api/v1/auth/sessions returns active sessions with safe metadata."""
    user = User(
        id=uuid.uuid4(),
        email="sessions_test@example.com",
        name="Session Test User",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # Login Device 1
    res1 = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "sessions_test@example.com",
            "password": "Password123!",
            "remember_me": True,
            "device_label": "MacBook Pro - Safari",
        },
    )
    assert res1.status_code == 200
    access_token = res1.json()["tokens"]["accessToken"]

    # Login Device 2
    res2 = await session_client.post(
        "/api/v1/auth/login",
        json={
            "email": "sessions_test@example.com",
            "password": "Password123!",
            "remember_me": False,
            "device_label": "Pixel 8 - Android",
        },
    )
    assert res2.status_code == 200

    # Query sessions
    sessions_res = await session_client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert sessions_res.status_code == 200
    sessions_data = sessions_res.json()["sessions"]
    assert len(sessions_data) == 2

    labels = {s["deviceLabel"] for s in sessions_data}
    assert labels == {"MacBook Pro - Safari", "Pixel 8 - Android"}

    # Ensure no secret fields leaked
    for s in sessions_data:
        assert "tokenHash" not in s
        assert "token_hash" not in s
        assert "password" not in s
        assert "id" in s
        assert "lastSeen" in s
        assert "createdAt" in s


@pytest.mark.anyio
async def test_sessions_user_isolation(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that a user can only view their own sessions and never another user's."""
    user1 = User(id=uuid.uuid4(), email="u1@example.com", name="User 1", hashed_password=hash_password("Password123!"), is_active=True)
    user2 = User(id=uuid.uuid4(), email="u2@example.com", name="User 2", hashed_password=hash_password("Password123!"), is_active=True)
    fake_db.users[user1.id] = user1
    fake_db.users[user2.id] = user2

    # Login User 1
    res1 = await session_client.post("/api/v1/auth/login", json={"email": "u1@example.com", "password": "Password123!", "device_label": "U1 Device"})
    u1_token = res1.json()["tokens"]["accessToken"]

    # Login User 2
    await session_client.post("/api/v1/auth/login", json={"email": "u2@example.com", "password": "Password123!", "device_label": "U2 Device"})

    # User 1 queries sessions
    res = await session_client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {u1_token}"})
    assert res.status_code == 200
    sessions = res.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["deviceLabel"] == "U1 Device"


@pytest.mark.anyio
async def test_revoke_specific_session_and_reject_refresh(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that revoking a session terminates that session stream while leaving other devices active."""
    user = User(id=uuid.uuid4(), email="revoke_test@example.com", name="Revoke Test", hashed_password=hash_password("Password123!"), is_active=True)
    fake_db.users[user.id] = user

    # Device 1
    d1_res = await session_client.post("/api/v1/auth/login", json={"email": "revoke_test@example.com", "password": "Password123!", "device_label": "Device 1"})
    d1_access = d1_res.json()["tokens"]["accessToken"]
    d1_refresh = d1_res.json()["tokens"]["refreshToken"]

    # Device 2
    d2_res = await session_client.post("/api/v1/auth/login", json={"email": "revoke_test@example.com", "password": "Password123!", "device_label": "Device 2"})
    d2_refresh = d2_res.json()["tokens"]["refreshToken"]

    # List sessions to obtain Device 2 session id
    list_res = await session_client.get("/api/v1/auth/sessions", headers={"Authorization": f"Bearer {d1_access}"})
    sessions = list_res.json()["sessions"]
    d2_session = next(s for s in sessions if s["deviceLabel"] == "Device 2")

    # Revoke Device 2 session using Device 1 credentials
    revoke_res = await session_client.delete(
        f"/api/v1/auth/sessions/{d2_session['id']}",
        headers={"Authorization": f"Bearer {d1_access}"},
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["message"] == "Session successfully revoked."

    # Device 2 refresh token is now revoked and must be rejected
    refresh_fail = await session_client.post("/api/v1/auth/refresh", json={"refreshToken": d2_refresh})
    assert refresh_fail.status_code == 401
    assert refresh_fail.json()["code"] == "TOKEN_REVOKED"

    # Device 1 refresh token is STILL VALID
    refresh_ok = await session_client.post("/api/v1/auth/refresh", json={"refreshToken": d1_refresh})
    assert refresh_ok.status_code == 200


@pytest.mark.anyio
async def test_cannot_revoke_another_users_session(session_client: AsyncClient, fake_db: FakeInMemoryDB):
    """Verify that User B cannot revoke User A's session."""
    user_a = User(id=uuid.uuid4(), email="victim@example.com", name="Victim", hashed_password=hash_password("Password123!"), is_active=True)
    user_b = User(id=uuid.uuid4(), email="attacker@example.com", name="Attacker", hashed_password=hash_password("Password123!"), is_active=True)
    fake_db.users[user_a.id] = user_a
    fake_db.users[user_b.id] = user_b

    # User A logs in
    res_a = await session_client.post("/api/v1/auth/login", json={"email": "victim@example.com", "password": "Password123!", "device_label": "Victim Laptop"})
    token_a = list(fake_db.tokens.values())[0]

    # User B logs in
    res_b = await session_client.post("/api/v1/auth/login", json={"email": "attacker@example.com", "password": "Password123!"})
    b_access = res_b.json()["tokens"]["accessToken"]

    # User B attempts to revoke User A's session
    attack_res = await session_client.delete(
        f"/api/v1/auth/sessions/{token_a.family_id}",
        headers={"Authorization": f"Bearer {b_access}"},
    )
    assert attack_res.status_code == 404
    assert attack_res.json()["code"] == "SESSION_NOT_FOUND"

    # Verify User A's token was NOT revoked
    assert token_a.is_revoked is False


@pytest.mark.anyio
async def test_session_endpoints_require_authentication(session_client: AsyncClient):
    """Verify that sessions endpoints return 401 when unauthenticated."""
    get_res = await session_client.get("/api/v1/auth/sessions")
    assert get_res.status_code == 401

    del_res = await session_client.delete(f"/api/v1/auth/sessions/{uuid.uuid4()}")
    assert del_res.status_code == 401
