import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict
from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password, hash_refresh_token
from app.main import app
from app.models.rate_limit import LoginRateLimit
from app.models.refresh_token import RefreshToken
from app.models.user import User


class FakeInMemoryDB:
    def __init__(self):
        self.users: Dict[uuid.UUID, User] = {}
        self.tokens: Dict[uuid.UUID, RefreshToken] = {}
        self.rate_limits: Dict[str, LoginRateLimit] = {}


from contextlib import asynccontextmanager
from sqlalchemy.exc import IntegrityError


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

    def scalar(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return FakeScalars(self._items)


class FakeAsyncSession:
    def __init__(self, db: FakeInMemoryDB):
        self.db = db
        self.pending_users: Dict[uuid.UUID, User] = {}
        self.pending_tokens: Dict[uuid.UUID, RefreshToken] = {}
        self.pending_rate_limits: Dict[str, LoginRateLimit] = {}
        self.simulate_integrity_error: bool = False

    def add(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, User):
            self.pending_users[obj.id] = obj
        elif isinstance(obj, RefreshToken):
            self.pending_tokens[obj.id] = obj
        elif isinstance(obj, LoginRateLimit):
            self.pending_rate_limits[obj.key] = obj

    async def delete(self, obj):
        if isinstance(obj, LoginRateLimit):
            self.db.rate_limits.pop(obj.key, None)
            self.pending_rate_limits.pop(obj.key, None)

    async def flush(self):
        if self.simulate_integrity_error:
            raise IntegrityError("duplicate key value violates unique constraint 'ix_users_email'", params={}, orig=Exception())
        # Check email uniqueness across persisted and pending
        for u in self.pending_users.values():
            for existing in self.db.users.values():
                if existing.id != u.id and existing.email == u.email:
                    raise IntegrityError(f"Key (email)=({u.email}) already exists.", params={}, orig=Exception())
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

    def in_transaction(self) -> bool:
        return True

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, stmt):
        # Flush pending changes to ensure visibility in queries
        self.db.users.update(self.pending_users)
        self.db.tokens.update(self.pending_tokens)
        self.db.rate_limits.update(self.pending_rate_limits)
        self.pending_users.clear()
        self.pending_tokens.clear()
        self.pending_rate_limits.clear()

        params = stmt.compile().params
        sql_str = str(stmt).lower()

        # 1. SELECT User queries
        if "from users" in sql_str:
            email_val = next((v for k, v in params.items() if "email" in k), None)
            if email_val is not None:
                matched = [u for u in self.db.users.values() if u.email == email_val]
                return FakeResult(matched)
            id_val = next((v for k, v in params.items() if "id" in k), None)
            if id_val is not None:
                matched = [u for u in self.db.users.values() if u.id == id_val]
                return FakeResult(matched)
            return FakeResult(list(self.db.users.values()))

        # 2. SELECT RefreshToken queries
        if "from refresh_tokens" in sql_str:
            hash_val = next((v for k, v in params.items() if "hash" in k), None)
            if "family_id" in sql_str and hash_val is not None and "select refresh_tokens.family_id" in sql_str:
                matched = [t.family_id for t in self.db.tokens.values() if t.token_hash == hash_val]
                return FakeResult(matched)
            if hash_val is not None:
                matched = [t for t in self.db.tokens.values() if t.token_hash == hash_val]
                return FakeResult(matched)
            user_val = next((v for k, v in params.items() if "user_id" in k or "user_1" in k), None)
            if user_val is not None and "is_revoked" in sql_str:
                now_utc = datetime.now(timezone.utc)
                matched = [
                    t for t in self.db.tokens.values()
                    if t.user_id == user_val and not t.is_revoked and t.expires_at > now_utc
                ]
                # Sort by last_seen descending
                matched.sort(key=lambda t: getattr(t, "last_seen", t.created_at), reverse=True)
                return FakeResult(matched)
            fam_or_id = next((v for k, v in params.items() if isinstance(v, uuid.UUID) and "user" not in k), None)
            if fam_or_id is not None:
                matched = [t for t in self.db.tokens.values() if t.family_id == fam_or_id or t.id == fam_or_id]
                return FakeResult(matched)
            return FakeResult(list(self.db.tokens.values()))

        # 3. UPDATE RefreshToken queries
        if "update refresh_tokens" in sql_str:
            fam_val = next((v for k, v in params.items() if "family" in k), None)
            user_val = next((v for k, v in params.items() if "user_id" in k), None)
            if fam_val is not None:
                for t in self.db.tokens.values():
                    if t.family_id == fam_val:
                        t.is_revoked = True
            elif user_val is not None:
                for t in self.db.tokens.values():
                    if t.user_id == user_val:
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
async def auth_client(fake_db):
    async def override_get_db():
        yield FakeAsyncSession(fake_db)

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_signup_success(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    response = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Alice Tester",
            "email": "alice@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "user" in data
    assert "tokens" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["name"] == "Alice Tester"
    assert "accessToken" in data["tokens"]
    assert "refreshToken" in data["tokens"]
    assert data["tokens"]["tokenType"] == "bearer"
    assert data["tokens"]["expiresIn"] == 900
    assert len(fake_db.users) == 1
    assert len(fake_db.tokens) == 1


@pytest.mark.anyio
async def test_signup_duplicate_email(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    # Pre-populate user
    user = User(
        id=uuid.uuid4(),
        email="existing@example.com",
        name="Existing",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    response = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Another Name",
            "email": "EXISTING@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "EMAIL_ALREADY_EXISTS"
    assert "already exists" in data["message"]


@pytest.mark.anyio
async def test_signup_validation_errors(auth_client: AsyncClient):
    # Password too short (<8)
    response = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Short Pass",
            "email": "short@example.com",
            "password": "short",
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"

    # Invalid email format
    response_email = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Bad Email",
            "email": "not-an-email",
            "password": "Password123!",
        },
    )
    assert response_email.status_code == 422
    assert response_email.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.anyio
async def test_register_alias_endpoint(auth_client: AsyncClient):
    response = await auth_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Alias User",
            "email": "alias@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "alias@example.com"
    assert "accessToken" in data["tokens"]


@pytest.mark.anyio
async def test_login_success(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="bob@example.com",
        name="Bob",
        hashed_password=hash_password("Secret123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "BOB@example.com", "password": "Secret123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "bob@example.com"
    assert "accessToken" in data["tokens"]
    assert "refreshToken" in data["tokens"]


@pytest.mark.anyio
async def test_login_wrong_password(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="bob@example.com",
        name="Bob",
        hashed_password=hash_password("Secret123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "INVALID_CREDENTIALS"


@pytest.mark.anyio
async def test_login_nonexistent_user_timing_attack_mitigation(auth_client: AsyncClient):
    with patch("app.api.v1.endpoints.auth.verify_dummy_password") as mock_dummy:
        mock_dummy.return_value = False
        response = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "Password123!"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "INVALID_CREDENTIALS"
        mock_dummy.assert_called_once_with("Password123!")


@pytest.mark.anyio
async def test_login_inactive_user(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        name="Inactive User",
        hashed_password=hash_password("Password123!"),
        is_active=False,
    )
    fake_db.users[user.id] = user

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "Password123!"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_INACTIVE"


@pytest.mark.anyio
async def test_refresh_token_rotation_success(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="refresh@example.com",
        name="Refresh Tester",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    raw_token = "raw-refresh-token-12345"
    token_hash = hash_refresh_token(raw_token)
    family_id = uuid.uuid4()
    refresh_token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=token_hash,
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[refresh_token_row.id] = refresh_token_row

    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": raw_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "accessToken" in data
    assert "refreshToken" in data
    assert data["refreshToken"] != raw_token

    # Verify old token was revoked
    assert refresh_token_row.is_revoked is True
    # Verify child token was inserted into fake_db
    child_tokens = [t for t in fake_db.tokens.values() if t.parent_id == refresh_token_row.id]
    assert len(child_tokens) == 1
    assert child_tokens[0].family_id == family_id
    assert child_tokens[0].is_revoked is False


@pytest.mark.anyio
async def test_refresh_token_invalid(auth_client: AsyncClient):
    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": "non-existent-token"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


@pytest.mark.anyio
async def test_refresh_token_expired(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    raw_token = "expired-token-raw"
    token_hash = hash_refresh_token(raw_token)
    refresh_token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        token_hash=token_hash,
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    fake_db.tokens[refresh_token_row.id] = refresh_token_row

    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": raw_token},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"
    assert refresh_token_row.is_revoked is True


@pytest.mark.anyio
async def test_refresh_token_reuse_detection(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    family_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Create already revoked token
    compromised_token = "compromised-token-raw"
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_refresh_token(compromised_token),
        parent_id=None,
        is_revoked=True,  # Already used!
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    # Create sibling active token in the same family
    active_sibling = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        family_id=family_id,
        token_hash=hash_refresh_token("active-sibling-token"),
        parent_id=token_row.id,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[active_sibling.id] = active_sibling

    # Attempting to refresh with compromised/reused token
    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": compromised_token},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_REVOKED"

    # Ensure all tokens in family were invalidated
    assert active_sibling.is_revoked is True


@pytest.mark.anyio
async def test_logout_with_refresh_token(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    raw_token = "logout-token"
    token_hash = hash_refresh_token(raw_token)
    family_id = uuid.uuid4()
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        family_id=family_id,
        token_hash=token_hash,
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    response = await auth_client.post(
        "/api/v1/auth/logout",
        json={"refreshToken": raw_token},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token_row.is_revoked is True


@pytest.mark.anyio
async def test_logout_with_bearer_token(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="logout_bearer@example.com",
        name="Logout Bearer",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=uuid.uuid4(),
        token_hash="some-hash",
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    access_token = create_access_token(user_id=user.id, email=user.email)

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token_row.is_revoked is True


@pytest.mark.anyio
async def test_logout_idempotent(auth_client: AsyncClient):
    response = await auth_client.post("/api/v1/auth/logout", json={})
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."


@pytest.mark.anyio
async def test_get_me_authenticated(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="me@example.com",
        name="Me User",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    access_token = create_access_token(user_id=user.id, email=user.email)

    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(user.id)
    assert data["name"] == "Me User"
    assert data["email"] == "me@example.com"


@pytest.mark.anyio
async def test_get_me_unauthorized_missing_token(auth_client: AsyncClient):
    response = await auth_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_get_me_expired_token(auth_client: AsyncClient):
    expired_token = create_access_token(
        user_id=uuid.uuid4(),
        email="expired@example.com",
        expires_delta=timedelta(seconds=-10),
    )
    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_EXPIRED"


@pytest.mark.anyio
async def test_get_me_tampered_token(auth_client: AsyncClient):
    valid_token = create_access_token(user_id=uuid.uuid4(), email="tamper@example.com")
    tampered_token = valid_token[:-4] + "zzzz"

    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_TOKEN"


@pytest.mark.anyio
async def test_get_me_inactive_user(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="inactive_me@example.com",
        name="Inactive Me",
        hashed_password=hash_password("Password123!"),
        is_active=False,
    )
    fake_db.users[user.id] = user

    access_token = create_access_token(user_id=user.id, email=user.email)

    response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_INACTIVE"


@pytest.mark.anyio
async def test_signup_integrity_error_race_condition(fake_db: FakeInMemoryDB):
    """Verify that a race condition triggering IntegrityError returns 409 EMAIL_ALREADY_EXISTS."""
    session = FakeAsyncSession(fake_db)
    session.simulate_integrity_error = True

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.post(
            "/api/v1/auth/signup",
            json={
                "name": "Race User",
                "email": "race@example.com",
                "password": "Password123!",
            },
        )
        assert response.status_code == 409
        data = response.json()
        assert data["code"] == "EMAIL_ALREADY_EXISTS"
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_signup_email_whitespace_normalization(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    response = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "  Whitespace User  ",
            "email": "   WHITESPACE.USER@EXAMPLE.COM   ",
            "password": "Password123!",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "whitespace.user@example.com"
    assert data["user"]["name"] == "Whitespace User"


@pytest.mark.anyio
async def test_refresh_token_inactive_user(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    user = User(
        id=uuid.uuid4(),
        email="inactive_refresher@example.com",
        name="Inactive Refresher",
        hashed_password=hash_password("Password123!"),
        is_active=False,
    )
    fake_db.users[user.id] = user

    raw_token = "inactive-refresh-token-raw"
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token(raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": raw_token},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ACCOUNT_INACTIVE"


@pytest.mark.anyio
async def test_refresh_token_user_not_found(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    # Refresh token references a user_id that does not exist in users table
    non_existent_user_id = uuid.uuid4()
    raw_token = "orphaned-refresh-token-raw"
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=non_existent_user_id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token(raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": raw_token},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_logout_without_body(auth_client: AsyncClient):
    response = await auth_client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."


@pytest.mark.anyio
async def test_logout_with_invalid_refresh_token(auth_client: AsyncClient):
    response = await auth_client.post(
        "/api/v1/auth/logout",
        json={"refreshToken": "completely-invalid-nonexistent-token"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."


@pytest.mark.anyio
async def test_logout_cross_user_credential_mismatch_forbidden(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 1: Authenticated user A cannot revoke user B's refresh token family.
    User A submits User B's refresh token -> returns 403 CREDENTIAL_MISMATCH,
    and User B's token remains unrevoked!
    """
    user_a = User(
        id=uuid.uuid4(),
        email="usera@example.com",
        name="User A",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="userb@example.com",
        name="User B",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user_a.id] = user_a
    fake_db.users[user_b.id] = user_b

    # User B's active refresh token
    user_b_raw_token = "user-b-refresh-token-raw"
    user_b_family = uuid.uuid4()
    token_b = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_b.id,
        family_id=user_b_family,
        token_hash=hash_refresh_token(user_b_raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_b.id] = token_b

    # User A's active refresh token
    user_a_raw_token = "user-a-refresh-token-raw"
    user_a_family = uuid.uuid4()
    token_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=user_a_family,
        token_hash=hash_refresh_token(user_a_raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_a.id] = token_a

    # User A generates valid access token
    access_token_a = create_access_token(user_id=user_a.id, email=user_a.email)

    # User A maliciously submits User B's refresh token in body
    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token_a}"},
        json={"refreshToken": user_b_raw_token},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "CREDENTIAL_MISMATCH"
    assert "does not belong to the authenticated user" in data["message"]

    # CRITICAL: Neither user's token family must be revoked!
    assert token_b.is_revoked is False
    assert token_a.is_revoked is False


@pytest.mark.anyio
async def test_logout_inactive_user_cannot_revoke_other_user_refresh_token(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 1b (Security regression): An inactive User A attempting to revoke User B's refresh token
    must NOT bypass the ownership check due to get_current_user_optional returning None.
    Must return HTTP 403 CREDENTIAL_MISMATCH and leave User B's token intact.
    """
    user_a = User(
        id=uuid.uuid4(),
        email="inactive_attacker@example.com",
        name="Inactive Attacker",
        hashed_password=hash_password("Password123!"),
        is_active=False,  # Inactive account
    )
    user_b = User(
        id=uuid.uuid4(),
        email="victim_user@example.com",
        name="Victim User",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user_a.id] = user_a
    fake_db.users[user_b.id] = user_b

    user_b_raw_token = "victim-refresh-token-raw"
    user_b_family = uuid.uuid4()
    token_b = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_b.id,
        family_id=user_b_family,
        token_hash=hash_refresh_token(user_b_raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_b.id] = token_b

    user_a_raw_token = "inactive-a-refresh-token"
    token_a = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token(user_a_raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_a.id] = token_a

    # Inactive User A holds a valid access token
    access_token_a = create_access_token(user_id=user_a.id, email=user_a.email)

    # Inactive User A attempts cross-user revocation of User B's session
    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token_a}"},
        json={"refreshToken": user_b_raw_token},
    )

    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "CREDENTIAL_MISMATCH"
    assert "does not belong to the authenticated user" in data["message"]

    # Neither token must be revoked
    assert token_b.is_revoked is False
    assert token_a.is_revoked is False


@pytest.mark.anyio
async def test_logout_inactive_user_own_token_success(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    An inactive user logging out with their own refresh token succeeds and revokes their own family.
    """
    user_a = User(
        id=uuid.uuid4(),
        email="inactive_self@example.com",
        name="Inactive Self",
        hashed_password=hash_password("Password123!"),
        is_active=False,
    )
    fake_db.users[user_a.id] = user_a

    raw_token = "inactive-self-token"
    family_id = uuid.uuid4()
    token = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=family_id,
        token_hash=hash_refresh_token(raw_token),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token.id] = token

    access_token = create_access_token(user_id=user_a.id, email=user_a.email)

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refreshToken": raw_token},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token.is_revoked is True


@pytest.mark.anyio
async def test_logout_inactive_user_no_body_revokes_active_tokens(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    An inactive user logging out with Bearer token only (no body) revokes their active tokens.
    """
    user_a = User(
        id=uuid.uuid4(),
        email="inactive_nobody@example.com",
        name="Inactive Nobody",
        hashed_password=hash_password("Password123!"),
        is_active=False,
    )
    fake_db.users[user_a.id] = user_a

    token = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=uuid.uuid4(),
        token_hash=hash_refresh_token("token-to-revoke"),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token.id] = token

    access_token = create_access_token(user_id=user_a.id, email=user_a.email)

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token.is_revoked is True


@pytest.mark.anyio
async def test_logout_matching_user_and_refresh_token_revokes_family(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 2: Legitimate logout with matching user & refresh token revokes the family.
    """
    user = User(
        id=uuid.uuid4(),
        email="legit_logout@example.com",
        name="Legit Logout",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    family_1 = uuid.uuid4()
    family_2 = uuid.uuid4()

    # Family 1 tokens (session being logged out)
    parent_token_1 = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_1,
        token_hash="parent-token-hash-1",
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    raw_token_child = "active-child-token-1"
    child_token_1 = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_1,
        token_hash=hash_refresh_token(raw_token_child),
        parent_id=parent_token_1.id,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[parent_token_1.id] = parent_token_1
    fake_db.tokens[child_token_1.id] = child_token_1

    # Family 2 token (another active session for same user)
    token_family_2 = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_2,
        token_hash="family-2-token-hash",
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_family_2.id] = token_family_2

    access_token = create_access_token(user_id=user.id, email=user.email)

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refreshToken": raw_token_child},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."

    # Both tokens in Family 1 are revoked
    assert parent_token_1.is_revoked is True
    assert child_token_1.is_revoked is True

    # Tokens in Family 2 remain active
    assert token_family_2.is_revoked is False


@pytest.mark.anyio
async def test_logout_with_expired_access_token_and_valid_refresh_token(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 3: Logout with expired access token + valid refresh token in body succeeds and revokes the family.
    """
    user = User(
        id=uuid.uuid4(),
        email="expired_access_logout@example.com",
        name="Expired Access",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    raw_refresh = "valid-refresh-for-expired-access"
    family_id = uuid.uuid4()
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=hash_refresh_token(raw_refresh),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    expired_access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        expires_delta=timedelta(seconds=-60),
    )

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {expired_access_token}"},
        json={"refreshToken": raw_refresh},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token_row.is_revoked is True


@pytest.mark.anyio
async def test_logout_with_malformed_access_token_and_valid_refresh_token(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 4: Logout with malformed access token + valid refresh token in body succeeds and revokes the family.
    """
    user = User(
        id=uuid.uuid4(),
        email="malformed_access_logout@example.com",
        name="Malformed Access",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    raw_refresh = "valid-refresh-for-malformed-access"
    family_id = uuid.uuid4()
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=hash_refresh_token(raw_refresh),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Bearer not.a.valid.jwt.token"},
        json={"refreshToken": raw_refresh},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token_row.is_revoked is True


@pytest.mark.anyio
async def test_logout_with_non_bearer_auth_header_and_valid_refresh_token(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 4b: Logout with non-Bearer auth header + valid refresh token in body succeeds and revokes the family.
    """
    user = User(
        id=uuid.uuid4(),
        email="non_bearer_logout@example.com",
        name="Non Bearer",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    raw_refresh = "valid-refresh-for-non-bearer"
    family_id = uuid.uuid4()
    token_row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        family_id=family_id,
        token_hash=hash_refresh_token(raw_refresh),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_row.id] = token_row

    response = await auth_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": "Basic dXNlcm5hbWU6cGFzc3dvcmQ="},
        json={"refreshToken": raw_refresh},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Successfully logged out."
    assert token_row.is_revoked is True


@pytest.mark.anyio
async def test_refresh_token_reuse_revokes_target_family_not_unrelated_family(auth_client: AsyncClient, fake_db: FakeInMemoryDB):
    """
    Test 5: Refresh token reuse revokes the target family and does not affect unrelated families.
    """
    user_a = User(
        id=uuid.uuid4(),
        email="reuse_a@example.com",
        name="Reuse A",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="reuse_b@example.com",
        name="Reuse B",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    fake_db.users[user_a.id] = user_a
    fake_db.users[user_b.id] = user_b

    family_a = uuid.uuid4()
    family_b = uuid.uuid4()

    compromised_token = "compromised-token-family-a"
    token_a_revoked = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=family_a,
        token_hash=hash_refresh_token(compromised_token),
        parent_id=None,
        is_revoked=True,  # Already rotated / used
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    token_a_active = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_a.id,
        family_id=family_a,
        token_hash=hash_refresh_token("sibling-token-family-a"),
        parent_id=token_a_revoked.id,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_a_revoked.id] = token_a_revoked
    fake_db.tokens[token_a_active.id] = token_a_active

    # Unrelated Family B for User B
    token_b_active = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_b.id,
        family_id=family_b,
        token_hash=hash_refresh_token("unrelated-token-family-b"),
        parent_id=None,
        is_revoked=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    fake_db.tokens[token_b_active.id] = token_b_active

    # Replay compromised token from Family A
    response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": compromised_token},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "TOKEN_REVOKED"

    # Family A sibling is revoked
    assert token_a_active.is_revoked is True
    # Family B unrelated token remains active
    assert token_b_active.is_revoked is False


@pytest.mark.anyio
async def test_concurrent_duplicate_signup_handling(auth_client: AsyncClient):
    """
    Test 8: Concurrent duplicate signup handling with identical email.
    One request succeeds (201) and the duplicate request fails with 409 EMAIL_ALREADY_EXISTS.
    """
    import asyncio

    signup_payload = {
        "name": "Concurrent User",
        "email": "concurrent_signup@example.com",
        "password": "Password123!",
    }

    # Issue two concurrent signup requests
    res1, res2 = await asyncio.gather(
        auth_client.post("/api/v1/auth/signup", json=signup_payload),
        auth_client.post("/api/v1/auth/signup", json=signup_payload),
    )

    statuses = sorted([res1.status_code, res2.status_code])
    assert statuses == [201, 409], f"Expected [201, 409], got {statuses}"

    conflict_res = res1 if res1.status_code == 409 else res2
    conflict_data = conflict_res.json()
    assert conflict_data["code"] == "EMAIL_ALREADY_EXISTS"
    assert "already exists" in conflict_data["message"]


@pytest.mark.anyio
async def test_contract_compliance_error_envelopes(auth_client: AsyncClient):
    """
    Test 10: Contract compliance (camelCase wire format, ApiErrorResponse envelope).
    """
    # 422 Validation Error format
    res_422 = await auth_client.post(
        "/api/v1/auth/signup",
        json={"name": "", "email": "invalid-email-address", "password": "short"},
    )
    assert res_422.status_code == 422
    data_422 = res_422.json()
    assert data_422["code"] == "VALIDATION_ERROR"
    assert "message" in data_422
    assert "detail" in data_422
    assert "isRetryable" in data_422
    assert data_422["isRetryable"] is False

    # 401 Unauthorized format
    res_401 = await auth_client.get("/api/v1/auth/me")
    assert res_401.status_code == 401
    data_401 = res_401.json()
    assert data_401["code"] == "UNAUTHORIZED"
    assert "message" in data_401
    assert "isRetryable" in data_401
    assert data_401["isRetryable"] is False


# ============================================================================
# US-01 Dedicated Acceptance Criteria Verification Tests
# ============================================================================

@pytest.mark.anyio
async def test_duplicate_normalized_email_sequential_registration_prevented(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that registering emails differing only in normalization
    (e.g. capitalization, leading/trailing whitespace) cannot create duplicate accounts,
    and that database-level email uniqueness is strictly enforced.
    """
    # 1. First registration with mixed-case email
    resp1 = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Original User",
            "email": "John.Doe@Example.com",
            "password": "Password123!",
        },
    )
    assert resp1.status_code == 201
    data1 = resp1.json()
    assert data1["user"]["email"] == "john.doe@example.com"
    assert len(fake_db.users) == 1

    # 2. Duplicate registration attempt with ALL CAPS email
    resp2 = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Impostor User",
            "email": "JOHN.DOE@EXAMPLE.COM",
            "password": "DifferentPassword123!",
        },
    )
    assert resp2.status_code == 409
    data2 = resp2.json()
    assert data2["code"] == "EMAIL_ALREADY_EXISTS"
    assert "already exists" in data2["message"]

    # 3. Duplicate registration attempt with whitespace-padded lowercase email
    resp3 = await auth_client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Whitespace Impostor",
            "email": "   john.doe@example.com   ",
            "password": "AnotherPassword123!",
        },
    )
    assert resp3.status_code == 409
    data3 = resp3.json()
    assert data3["code"] == "EMAIL_ALREADY_EXISTS"

    # 4. Confirm only 1 user exists in the database
    assert len(fake_db.users) == 1
    persisted_user = list(fake_db.users.values())[0]
    assert persisted_user.email == "john.doe@example.com"


@pytest.mark.anyio
async def test_wrong_password_generic_error_indistinguishable_from_nonexistent_user(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that incorrect credentials return a generic error without
    revealing whether an account exists. Both wrong password for an existing account
    and login for a non-existent account must return identical status codes,
    error envelopes, codes, and sanitized messages.
    """
    # Create legitimate user
    user = User(
        id=uuid.uuid4(),
        email="realuser@example.com",
        name="Real User",
        hashed_password=hash_password("LegitPassword123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # Attempt 1: Existing user with WRONG password
    resp_wrong_pw = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "realuser@example.com", "password": "WrongPassword999!"},
    )

    # Attempt 2: NON-EXISTENT user
    resp_nonexistent = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "WrongPassword999!"},
    )

    # Both must return HTTP 401 Unauthorized
    assert resp_wrong_pw.status_code == 401
    assert resp_nonexistent.status_code == 401

    data_wrong_pw = resp_wrong_pw.json()
    data_nonexistent = resp_nonexistent.json()

    # Exact payload identity: no timing/account disclosure leak
    assert data_wrong_pw["code"] == "INVALID_CREDENTIALS"
    assert data_nonexistent["code"] == "INVALID_CREDENTIALS"
    assert data_wrong_pw["message"] == "Invalid email or password."
    assert data_nonexistent["message"] == "Invalid email or password."
    assert data_wrong_pw["detail"] is None
    assert data_nonexistent["detail"] is None
    assert data_wrong_pw["isRetryable"] is False
    assert data_nonexistent["isRetryable"] is False

    # Responses must be completely indistinguishable
    assert data_wrong_pw == data_nonexistent


@pytest.mark.anyio
async def test_login_rate_limiting_triggered_after_max_failed_attempts(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Check whether repeated failed login attempts are actually rate-limited.
    Verify that repeated failed login attempts trigger HTTP 429 when the configured
    limit (default: 5) is exceeded, returning the standardized error envelope
    and Retry-After header.
    """
    user = User(
        id=uuid.uuid4(),
        email="ratelimit_target@example.com",
        name="Target User",
        hashed_password=hash_password("CorrectPassword123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # Execute 5 consecutive failed login attempts (each returns 401)
    for attempt in range(1, 6):
        resp = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit_target@example.com", "password": f"BadPassword{attempt}!"},
        )
        assert resp.status_code == 401, f"Attempt {attempt} should return 401, got {resp.status_code}"
        assert resp.json()["code"] == "INVALID_CREDENTIALS"

    # Attempt 6: Exceeds max attempts (5) -> must return HTTP 429 Too Many Requests
    resp_rate_limited = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit_target@example.com", "password": "BadPassword6!"},
    )
    assert resp_rate_limited.status_code == 429
    data = resp_rate_limited.json()
    assert data["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Too many failed login attempts" in data["message"]
    assert data["isRetryable"] is False
    assert "retry-after" in resp_rate_limited.headers
    retry_after = int(resp_rate_limited.headers["retry-after"])
    assert retry_after > 0


@pytest.mark.anyio
async def test_login_rate_limiting_blocks_even_with_correct_password_while_locked(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that once an account is locked out by rate limiting,
    subsequent attempts even with the CORRECT password are rejected with HTTP 429.
    """
    user = User(
        id=uuid.uuid4(),
        email="locked_user@example.com",
        name="Locked User",
        hashed_password=hash_password("SuperSecretPassword123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # 5 failed attempts to lock account
    for _ in range(5):
        resp = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "locked_user@example.com", "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    # Attempt with CORRECT password while rate limited
    resp_correct_pw = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "locked_user@example.com", "password": "SuperSecretPassword123!"},
    )
    assert resp_correct_pw.status_code == 429
    assert resp_correct_pw.json()["code"] == "RATE_LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_login_rate_limiting_isolated_per_account(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that rate limiting on one account does not block or impact
    login attempts for another legitimate account.
    """
    user_a = User(
        id=uuid.uuid4(),
        email="victim@example.com",
        name="Victim",
        hashed_password=hash_password("VictimPassword123!"),
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email="innocent@example.com",
        name="Innocent",
        hashed_password=hash_password("InnocentPassword123!"),
        is_active=True,
    )
    fake_db.users[user_a.id] = user_a
    fake_db.users[user_b.id] = user_b

    # Lock out user_a with 5 failed attempts
    for _ in range(5):
        await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "victim@example.com", "password": "WrongPassword!"},
        )

    # user_a is now rate-limited
    res_a = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "WrongPassword!"},
    )
    assert res_a.status_code == 429

    # user_b logs in with correct password -> must succeed with 200
    res_b = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "innocent@example.com", "password": "InnocentPassword123!"},
    )
    assert res_b.status_code == 200
    assert res_b.json()["user"]["email"] == "innocent@example.com"


@pytest.mark.anyio
async def test_login_rate_limiting_resets_on_successful_login(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that a successful login resets the failed attempts counter
    so that intermittent mistakes do not build up to premature lockout.
    """
    user = User(
        id=uuid.uuid4(),
        email="clumsy_user@example.com",
        name="Clumsy User",
        hashed_password=hash_password("ClumsyPassword123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # 3 failed attempts (below limit of 5)
    for _ in range(3):
        res = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "clumsy_user@example.com", "password": "TypoPassword!"},
        )
        assert res.status_code == 401

    # Legitimate login -> 200 OK and counter reset
    res_success = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "clumsy_user@example.com", "password": "ClumsyPassword123!"},
    )
    assert res_success.status_code == 200

    # Rate limit record should be cleared or reset
    assert "clumsy_user@example.com" not in fake_db.rate_limits

    # Another 3 failed attempts must not trigger 429 because count was reset
    for _ in range(3):
        res = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "clumsy_user@example.com", "password": "TypoPassword!"},
        )
        assert res.status_code == 401


@pytest.mark.anyio
async def test_login_rate_limiting_lockout_expires_after_window(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that requests behave correctly after the lockout window has elapsed.
    """
    user = User(
        id=uuid.uuid4(),
        email="lockout_expiry@example.com",
        name="Lockout Expiry",
        hashed_password=hash_password("CorrectSecret123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    # Lock account with 5 failed attempts
    for _ in range(5):
        await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "lockout_expiry@example.com", "password": "WrongPassword!"},
        )

    # Verify locked
    res_locked = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "lockout_expiry@example.com", "password": "WrongPassword!"},
    )
    assert res_locked.status_code == 429

    # Simulate lockout window expiration (e.g. 901 seconds ago)
    record = fake_db.rate_limits.get("lockout_expiry@example.com")
    assert record is not None
    record.last_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=901)

    # Next attempt after window expiry should be allowed through (not 429)
    res_after_window = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "lockout_expiry@example.com", "password": "CorrectSecret123!"},
    )
    assert res_after_window.status_code == 200


@pytest.mark.anyio
async def test_login_rate_limiting_applies_to_nonexistent_users(
    auth_client: AsyncClient,
):
    """
    US-01: Verify that rate limiting also protects non-existent accounts from
    brute force/enumeration attacks without leaking account existence.
    """
    # 5 failed attempts for non-existent account
    for _ in range(5):
        res = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody_special@example.com", "password": "WrongPassword!"},
        )
        assert res.status_code == 401
        assert res.json()["code"] == "INVALID_CREDENTIALS"

    # 6th attempt triggers 429
    res_rate_limited = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody_special@example.com", "password": "WrongPassword!"},
    )
    assert res_rate_limited.status_code == 429
    assert res_rate_limited.json()["code"] == "RATE_LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_login_rate_limiting_case_insensitive(
    auth_client: AsyncClient,
    fake_db: FakeInMemoryDB,
):
    """
    US-01: Verify that email normalization ensures varying capitalization
    all contributes to the same rate limiting counter.
    """
    user = User(
        id=uuid.uuid4(),
        email="case_test@example.com",
        name="Case Test",
        hashed_password=hash_password("CasePassword123!"),
        is_active=True,
    )
    fake_db.users[user.id] = user

    cased_emails = [
        "CASE_TEST@EXAMPLE.COM",
        "Case_Test@Example.Com",
        "case_TEST@example.com",
        "cAsE_tEsT@eXaMpLe.CoM",
        "case_test@example.com",
    ]

    for email_variant in cased_emails:
        res = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": email_variant, "password": "WrongPassword!"},
        )
        assert res.status_code == 401

    # 6th attempt with yet another casing variation must trigger 429
    res_6 = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "   CASE_test@EXAMPLE.com   ", "password": "WrongPassword!"},
    )
    assert res_6.status_code == 429
    assert res_6.json()["code"] == "RATE_LIMIT_EXCEEDED"



