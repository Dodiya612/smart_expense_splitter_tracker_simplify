"""T-50: change password, session revocation and the password_changed notice.

Runs on the in-memory fake session from tests/test_sessions.py (no database). The same
flow on a real PostgreSQL database (row locks, ORM flushes, the notification CHECK
constraint and the "cannot be switched off" rule) is in tests/test_change_password_pg.py.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import rate_limiter
from app.core.database import get_db
from app.core.password_strength import estimate_password_strength
from app.core.security import create_access_token, hash_password, verify_password
from app.main import app
from app.models.notification import NOTIFICATION_KINDS, SECURITY_KINDS
from app.models.user import User
from app.schemas.notification import NotificationPreferencesUpdateRequest
from app.services.notifications import render_notification
from tests.notification_fakes import get_emitted_notifications
from tests.test_sessions import FakeAsyncSession, FakeInMemoryDB

OLD_PASSWORD = "Password123!"
NEW_PASSWORD = "Monsoon-Chai-4-Two!"
EMAIL = "priya.patel@example.in"
URL = "/api/v1/auth/change-password"
FIXTURE = Path(__file__).parent / "fixtures" / "password_strength_cases.json"


@pytest.fixture
def fake_db() -> FakeInMemoryDB:
    return FakeInMemoryDB()


@pytest.fixture
async def client(fake_db: FakeInMemoryDB):
    async def override_get_db():
        yield FakeAsyncSession(fake_db)

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


def add_user(fake_db: FakeInMemoryDB, email: str = EMAIL, name: str = "Priya Patel") -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        name=name,
        hashed_password=hash_password(OLD_PASSWORD),
        is_active=True,
    )
    fake_db.users[user.id] = user
    return user


async def login(client: AsyncClient, email: str = EMAIL, password: str = OLD_PASSWORD, device: str = "Phone"):
    res = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password, "device_label": device}
    )
    assert res.status_code == 200, res.text
    return res.json()["tokens"]


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def body(current: str = OLD_PASSWORD, new: str = NEW_PASSWORD, confirm: str | None = None) -> dict[str, str]:
    return {
        "currentPassword": current,
        "newPassword": new,
        "confirmNewPassword": new if confirm is None else confirm,
    }


def assert_unchanged(user: User) -> None:
    assert verify_password(OLD_PASSWORD, user.hashed_password)
    assert (user.token_version or 0) == 0
    assert [n for n in get_emitted_notifications() if n.kind == "password_changed"] == []


def assert_no_password_in(text: str) -> None:
    for secret in (OLD_PASSWORD, NEW_PASSWORD, "wrong-Password-99"):
        assert secret not in text


# ==============================================================================
# Validation
# ==============================================================================


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (body(new="Sh0rt!x", confirm="Sh0rt!x"), "PASSWORD_TOO_SHORT"),
        (body(new="aaaaaaaaaaaa"), "WEAK_PASSWORD"),
        (body(new="Password123456"), "WEAK_PASSWORD"),
        (body(new="PriyaPatel2024"), "WEAK_PASSWORD"),
        (body(confirm="Monsoon-Chai-4-Too!"), "PASSWORD_MISMATCH"),
        (body(new=OLD_PASSWORD + "x", confirm=OLD_PASSWORD + "x"), "WEAK_PASSWORD"),
    ],
)
async def test_new_password_rules_are_enforced_server_side(client, fake_db, payload, code):
    user = add_user(fake_db)
    tokens = await login(client)
    res = await client.post(URL, json=payload, headers=bearer(tokens["accessToken"]))
    assert res.status_code == 422
    assert res.json()["code"] == code
    assert_no_password_in(res.text)
    assert_unchanged(user)


async def test_weak_password_error_explains_what_to_improve(client, fake_db):
    add_user(fake_db)
    tokens = await login(client)
    res = await client.post(URL, json=body(new="aaaaaaaaaaaa"), headers=bearer(tokens["accessToken"]))
    data = res.json()
    assert "/4" in data["message"]
    assert data["detail"] and all(item["loc"] == ["body", "newPassword"] for item in data["detail"])


@pytest.mark.parametrize("field", ["currentPassword", "newPassword", "confirmNewPassword"])
async def test_empty_or_missing_fields_are_rejected(client, fake_db, field):
    user = add_user(fake_db)
    tokens = await login(client)
    empty = {**body(), field: ""}
    res = await client.post(URL, json=empty, headers=bearer(tokens["accessToken"]))
    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_ERROR"
    missing = body()
    del missing[field]
    res = await client.post(URL, json=missing, headers=bearer(tokens["accessToken"]))
    assert res.status_code == 422
    assert_unchanged(user)


async def test_new_password_equal_to_current_is_rejected(client, fake_db, monkeypatch):
    strong_old = "Xk9#mQ2v!Lp7"
    user = add_user(fake_db)
    user.hashed_password = hash_password(strong_old)
    tokens = await login(client, password=strong_old)
    res = await client.post(
        URL, json=body(current=strong_old, new=strong_old), headers=bearer(tokens["accessToken"])
    )
    assert res.status_code == 422
    assert res.json()["code"] == "PASSWORD_UNCHANGED"
    assert verify_password(strong_old, user.hashed_password)


async def test_oversized_password_is_rejected_without_echoing_it(client, fake_db):
    add_user(fake_db)
    tokens = await login(client)
    huge = "Zq9!" * 40
    res = await client.post(URL, json=body(new=huge), headers=bearer(tokens["accessToken"]))
    assert res.status_code == 422
    assert huge not in res.text


# ==============================================================================
# Authentication and current-password verification
# ==============================================================================


async def test_incorrect_current_password_is_rejected_and_changes_nothing(client, fake_db):
    user = add_user(fake_db)
    phone = await login(client, device="Phone")
    laptop = await login(client, device="Laptop")

    res = await client.post(
        URL, json=body(current="wrong-Password-99"), headers=bearer(phone["accessToken"])
    )

    # 400, not 401: the mobile client treats 401 as "session invalid" and would refresh.
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_CURRENT_PASSWORD"
    assert_no_password_in(res.text)
    assert_unchanged(user)
    assert not any(t.is_revoked for t in fake_db.tokens.values())
    # Both sessions still work.
    for tokens in (phone, laptop):
        assert (await client.get("/api/v1/auth/me", headers=bearer(tokens["accessToken"]))).status_code == 200


async def test_unauthenticated_requests_are_rejected(client, fake_db):
    user = add_user(fake_db)
    assert (await client.post(URL, json=body())).status_code == 401
    bad = await client.post(URL, json=body(), headers=bearer("not-a-token"))
    assert bad.status_code == 401
    assert_unchanged(user)


async def test_access_token_without_session_claim_must_refresh_first(client, fake_db):
    """Tokens issued before T-50 carry no sid; the client's refresh-and-retry fixes that."""
    user = add_user(fake_db)
    await login(client)
    legacy = create_access_token(user.id, user.email)
    res = await client.post(URL, json=body(), headers=bearer(legacy))
    assert res.status_code == 401
    assert res.json()["code"] == "SESSION_NOT_IDENTIFIED"
    assert_unchanged(user)


async def test_access_token_for_an_already_revoked_session_cannot_change_password(client, fake_db):
    user = add_user(fake_db)
    tokens = await login(client)
    for token in fake_db.tokens.values():
        token.is_revoked = True
    res = await client.post(URL, json=body(), headers=bearer(tokens["accessToken"]))
    assert res.status_code == 401
    assert res.json()["code"] == "TOKEN_REVOKED"
    assert_unchanged(user)


async def test_cannot_change_another_users_password(client, fake_db):
    priya = add_user(fake_db)
    arjun = add_user(fake_db, email="arjun.rao@example.in", name="Arjun Rao")
    priya_tokens = await login(client)
    arjun_tokens = await login(client, email="arjun.rao@example.in", device="Arjun phone")

    # The account always comes from the access token; extra body fields are ignored.
    payload = {**body(), "userId": str(arjun.id), "email": arjun.email}
    res = await client.post(URL, json=payload, headers=bearer(priya_tokens["accessToken"]))

    assert res.status_code == 200
    assert verify_password(NEW_PASSWORD, priya.hashed_password)
    assert verify_password(OLD_PASSWORD, arjun.hashed_password)
    assert (arjun.token_version or 0) == 0
    assert (await client.get("/api/v1/auth/me", headers=bearer(arjun_tokens["accessToken"]))).status_code == 200
    refresh = await client.post("/api/v1/auth/refresh", json={"refreshToken": arjun_tokens["refreshToken"]})
    assert refresh.status_code == 200
    # Arjun changing his own password affects only his account.
    res = await client.post(
        URL, json=body(new="Arjun-Kite-River-81"), headers=bearer(arjun_tokens["accessToken"])
    )
    assert res.status_code == 200
    assert verify_password("Arjun-Kite-River-81", arjun.hashed_password)
    assert verify_password(NEW_PASSWORD, priya.hashed_password)
    assert priya.token_version == 1


# ==============================================================================
# Success, session revocation and the current device
# ==============================================================================


async def test_success_updates_password_and_revokes_every_other_session(client, fake_db):
    user = add_user(fake_db)
    phone = await login(client, device="Phone")  # the device that changes the password
    laptop = await login(client, device="Laptop")
    tablet = await login(client, device="Tablet")

    res = await client.post(URL, json=body(), headers=bearer(phone["accessToken"]))

    assert res.status_code == 200, res.text
    data = res.json()
    assert_no_password_in(res.text)
    assert data["revokedSessions"] == 2
    new_tokens = data["tokens"]
    assert verify_password(NEW_PASSWORD, user.hashed_password)
    assert not verify_password(OLD_PASSWORD, user.hashed_password)
    assert user.token_version == 1

    # Other devices: access tokens are refused at once, on every protected route ...
    for tokens in (laptop, tablet):
        for path in ("/api/v1/auth/me", "/api/v1/auth/sessions", "/api/v1/notifications"):
            denied = await client.get(path, headers=bearer(tokens["accessToken"]))
            assert denied.status_code == 401, path
            assert denied.json()["code"] == "TOKEN_REVOKED"
        # ... and their refresh tokens can no longer mint new access tokens.
        refresh = await client.post("/api/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
        assert refresh.status_code == 401
        assert refresh.json()["code"] == "TOKEN_REVOKED"

    # This device: the old access token is stale too, the new pair works.
    stale = await client.get("/api/v1/auth/me", headers=bearer(phone["accessToken"]))
    assert stale.status_code == 401
    me = await client.get("/api/v1/auth/me", headers=bearer(new_tokens["accessToken"]))
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL
    sessions = await client.get("/api/v1/auth/sessions", headers=bearer(new_tokens["accessToken"]))
    assert [s["deviceLabel"] for s in sessions.json()["sessions"]] == ["Phone"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refreshToken": new_tokens["refreshToken"]})
    assert rotated.status_code == 200
    me_again = await client.get("/api/v1/auth/me", headers=bearer(rotated.json()["accessToken"]))
    assert me_again.status_code == 200

    # The old password no longer logs in; the new one does.
    old_login = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": OLD_PASSWORD})
    assert old_login.status_code == 401
    await login(client, password=NEW_PASSWORD, device="New laptop")


async def test_this_devices_previous_refresh_token_is_rotated_out(client, fake_db):
    add_user(fake_db)
    phone = await login(client, device="Phone")
    res = await client.post(URL, json=body(), headers=bearer(phone["accessToken"]))
    assert res.status_code == 200
    # A copy of the pre-change refresh token (for example a stolen one) is now dead. Using it
    # is treated as reuse, which (by the existing refresh design) ends that family too.
    old = await client.post("/api/v1/auth/refresh", json={"refreshToken": phone["refreshToken"]})
    assert old.status_code == 401


async def test_password_can_be_changed_again_with_the_new_tokens(client, fake_db):
    user = add_user(fake_db)
    phone = await login(client)
    first = await client.post(URL, json=body(), headers=bearer(phone["accessToken"]))
    tokens = first.json()["tokens"]
    second = await client.post(
        URL,
        json=body(current=NEW_PASSWORD, new="Second-Rain-Kite-77"),
        headers=bearer(tokens["accessToken"]),
    )
    assert second.status_code == 200
    assert user.token_version == 2
    assert verify_password("Second-Rain-Kite-77", user.hashed_password)


async def test_malformed_token_version_claim_is_rejected(client, fake_db):
    import jwt

    from app.core.config import settings

    user = add_user(fake_db)
    token = create_access_token(user.id, user.email)
    claims = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                        audience=settings.JWT_AUDIENCE, issuer=settings.JWT_ISSUER)
    claims["tv"] = "0"
    forged = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    res = await client.get("/api/v1/auth/me", headers=bearer(forged))
    assert res.status_code == 401
    assert res.json()["code"] == "INVALID_TOKEN"


async def test_attempts_are_rate_limited_per_user(client, fake_db):
    user = add_user(fake_db)
    tokens = await login(client)
    limit = rate_limiter.get_policy("password_change_user").limit
    for _ in range(limit):
        res = await client.post(URL, json=body(current="wrong-Password-99"), headers=bearer(tokens["accessToken"]))
        assert res.status_code == 400
    blocked = await client.post(URL, json=body(), headers=bearer(tokens["accessToken"]))
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert_unchanged(user)


# ==============================================================================
# Notification centre
# ==============================================================================


async def test_success_stores_one_password_changed_notice_for_the_user(client, fake_db):
    user = add_user(fake_db)
    phone = await login(client, device="Phone")
    await login(client, device="Laptop")
    res = await client.post(URL, json=body(), headers=bearer(phone["accessToken"]))
    assert res.status_code == 200
    assert res.json()["message"] == "Your password has been changed."

    notices = [n for n in get_emitted_notifications() if n.kind == "password_changed"]
    assert len(notices) == 1
    notice = notices[0]
    assert notice.user_id == str(user.id)
    assert notice.group_id is None
    assert notice.payload == {"revoked_sessions": 1}
    assert notice.title == "Password changed"
    assert "signed out on 1 other device." in notice.body
    assert_no_password_in(json.dumps(notice.payload) + notice.title + notice.body)


async def test_failed_changes_produce_no_notice(client, fake_db):
    add_user(fake_db)
    tokens = await login(client)
    for payload in (body(current="wrong-Password-99"), body(new="aaaaaaaaaaaa"), body(confirm="nope-nope-nope")):
        await client.post(URL, json=payload, headers=bearer(tokens["accessToken"]))
    assert get_emitted_notifications() == []


def test_password_changed_is_a_security_kind_that_cannot_be_switched_off():
    assert "password_changed" in NOTIFICATION_KINDS
    assert "password_changed" in SECURITY_KINDS
    with pytest.raises(ValueError):
        NotificationPreferencesUpdateRequest(preferences=[{"kind": "password_changed", "enabled": False}])
    ok = NotificationPreferencesUpdateRequest(preferences=[{"kind": "password_changed", "enabled": True}])
    assert ok.preferences[0].enabled is True


def test_notice_text_without_other_sessions():
    title, text = render_notification("password_changed", {"revoked_sessions": 0})
    assert title == "Password changed"
    assert "signed out" not in text
    _, plural = render_notification("password_changed", {"revoked_sessions": 3})
    assert "3 other devices" in plural


# ==============================================================================
# Strength estimator (shared with the mobile meter)
# ==============================================================================


def test_strength_matches_the_shared_fixture():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 20
    for case in cases:
        result = estimate_password_strength(case["password"], case["user_inputs"])
        assert (result.score, result.effective_length, result.is_common) == (
            case["score"], case["effective_length"], case["is_common"]
        ), case["password"]


@pytest.mark.parametrize(
    ("password", "minimum", "maximum"),
    [
        ("password12", 0, 1),
        ("Password123!", 0, 1),
        ("qwertyuiop12", 0, 1),
        ("1111111111", 0, 0),
        ("Xk9#mQ2v!Lp7", 3, 4),
        ("correct horse battery staple", 3, 4),
        ("Monsoon-Chai-4-Two!", 3, 4),
    ],
)
def test_strength_ranks_common_patterns_low_and_random_or_long_high(password, minimum, maximum):
    score = estimate_password_strength(password).score
    assert minimum <= score <= maximum


def test_strength_penalises_the_users_own_name_and_email():
    plain = estimate_password_strength("Priyapatel#2024x")
    personal = estimate_password_strength("Priyapatel#2024x", ("Priya Patel", "priya.patel@example.in"))
    assert personal.score < plain.score
    assert any("name or email" in hint for hint in personal.feedback)
