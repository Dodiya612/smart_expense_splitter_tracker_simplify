"""Rate limits on login, signup, register and refresh (T-39).

Reuses the in-memory auth fake database from tests/test_auth_api.py and the in-memory counter
store from conftest. Address-scoped limits need a trusted client-address header, so these tests
configure ``TRUSTED_CLIENT_IP_HEADER`` and send ``X-Test-Client-IP`` the way a verified proxy
would; one test shows what happens when no header is configured.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from app.core.config import settings
from app.core.rate_limiter import get_policy, hash_identifier
from app.core.security import hash_password
from app.models.user import User
from tests import rate_limit_fakes as fakes
from tests import test_auth_api as auth

# Reuse the auth fixtures (fake DB and a client that presents itself as 203.0.113.10).
fake_db = auth.fake_db
auth_client = auth.auth_client

IP_HEADER = "X-Test-Client-IP"
VICTIM = "victim@example.com"
GOOD = "CorrectPassword123!"


@pytest.fixture(autouse=True)
def trusted_header(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", IP_HEADER)


def add_user(fake_db, email: str = VICTIM, password: str = GOOD) -> User:
    user = User(
        id=uuid.uuid4(), email=email, name="Test User",
        hashed_password=hash_password(password), is_active=True,
    )
    fake_db.users[user.id] = user
    return user


async def login(client, email: str, password: str = "wrong-password", ip: str | None = None):
    headers = {IP_HEADER: ip} if ip else None
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )


# ------------------------------------------------------------------------------
# Login: account-and-address, address ceiling, account ceiling
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_429_envelope_has_retry_after_and_is_retryable(auth_client, fake_db):
    add_user(fake_db)
    for _ in range(5):
        assert (await login(auth_client, VICTIM)).status_code == 401
    blocked = await login(auth_client, VICTIM)
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED" and body["isRetryable"] is True
    assert "Too many failed login attempts" in body["message"]
    retry_after = int(blocked.headers["retry-after"])
    assert 0 < retry_after <= 900
    assert f"{retry_after} seconds" in body["message"]


@pytest.mark.anyio
async def test_an_attacker_at_one_address_cannot_lock_the_victim_out_elsewhere(auth_client, fake_db):
    add_user(fake_db)
    for _ in range(5):
        assert (await login(auth_client, VICTIM, ip="198.51.100.1")).status_code == 401
    assert (await login(auth_client, VICTIM, ip="198.51.100.1")).status_code == 429  # attacker blocked
    # The victim, from their own address, still gets in with the right password.
    ok = await login(auth_client, VICTIM, GOOD, ip="203.0.113.50")
    assert ok.status_code == 200 and ok.json()["user"]["email"] == VICTIM


@pytest.mark.anyio
async def test_a_blocked_address_cannot_get_in_even_with_the_correct_password(auth_client, fake_db):
    add_user(fake_db)
    for _ in range(5):
        await login(auth_client, VICTIM, ip="198.51.100.1")
    blocked = await login(auth_client, VICTIM, GOOD, ip="198.51.100.1")
    assert blocked.status_code == 429


@pytest.mark.anyio
async def test_address_ceiling_stops_one_address_trying_many_accounts(auth_client):
    # 20 different accounts, one attempt each (so no per-account limit is near) from one address.
    for i in range(20):
        assert (await login(auth_client, f"user{i}@example.com", ip="198.51.100.9")).status_code == 401
    over = await login(auth_client, "user99@example.com", ip="198.51.100.9")
    assert over.status_code == 429 and int(over.headers["retry-after"]) > 0
    # A different address is unaffected.
    assert (await login(auth_client, "user99@example.com", ip="198.51.100.10")).status_code == 401


@pytest.mark.anyio
async def test_account_ceiling_stops_distributed_guessing_but_needs_many_addresses(auth_client, fake_db):
    add_user(fake_db)
    # 6 addresses x 5 failures each = 30: still allowed (each address is at its own limit).
    for n in range(6):
        for _ in range(5):
            assert (await login(auth_client, VICTIM, ip=f"198.51.100.{n + 20}")).status_code == 401
    # The 31st attempt on the account, from a brand-new address, is stopped by the ceiling.
    over = await login(auth_client, VICTIM, GOOD, ip="198.51.100.99")
    assert over.status_code == 429 and over.json()["code"] == "RATE_LIMIT_EXCEEDED"


@pytest.mark.anyio
async def test_attempts_from_other_addresses_below_the_ceiling_do_not_block_the_owner(auth_client, fake_db):
    add_user(fake_db)
    for n in range(4):  # 20 failures from 4 attackers: below the 30 ceiling
        for _ in range(5):
            await login(auth_client, VICTIM, ip=f"198.51.100.{n + 40}")
    assert (await login(auth_client, VICTIM, GOOD, ip="203.0.113.50")).status_code == 200


@pytest.mark.anyio
async def test_successful_login_clears_pair_and_account_buckets_but_not_the_address_bucket(
    auth_client, fake_db
):
    add_user(fake_db)
    for _ in range(4):
        await login(auth_client, VICTIM)
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 200
    assert fakes.count_for("login_pair") == 0       # account-and-address bucket cleared
    assert fakes.count_for("login_account") == 0    # account-only bucket cleared
    # The address-wide bucket is shared with other users behind the address: it is NOT cleared,
    # only this one successful attempt is given back (4 failures remain).
    assert fakes.count_for("login_ip") == 4
    # With the pair counter cleared, four more mistakes are fine again.
    for _ in range(4):
        assert (await login(auth_client, VICTIM)).status_code == 401


@pytest.mark.anyio
async def test_successful_login_clears_the_account_bucket_even_without_a_trusted_address(
    auth_client, fake_db, monkeypatch
):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", None)
    add_user(fake_db)
    for _ in range(3):
        await login(auth_client, VICTIM)
    assert fakes.count_for("login_account") == 3
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 200
    assert fakes.count_for("login_account") == 0


@pytest.mark.anyio
async def test_failed_and_blocked_logins_never_clear_anything(auth_client, fake_db):
    add_user(fake_db)
    for _ in range(5):
        await login(auth_client, VICTIM)
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 429  # blocked, correct password
    assert fakes.count_for("login_pair") == 6 and fakes.count_for("login_account") == 6


@pytest.mark.anyio
async def test_limit_expires_with_the_window(auth_client, fake_db):
    add_user(fake_db)
    for _ in range(5):
        await login(auth_client, VICTIM)
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 429
    fakes.advance(900)
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 200


@pytest.mark.anyio
async def test_stored_counters_contain_no_plain_email_or_address(auth_client, fake_db):
    add_user(fake_db)
    await login(auth_client, VICTIM)
    keys = {h for (_s, h, _w) in fakes._rows}
    assert hash_identifier("login_account", VICTIM) in keys
    assert hash_identifier("login_pair", f"{VICTIM}|203.0.113.10") in keys
    assert hash_identifier("login_ip", "203.0.113.10") in keys
    assert not any(VICTIM in k or "203.0.113.10" in k for k in keys)


# ------------------------------------------------------------------------------
# Spoofed forwarding headers and an unconfigured trusted header
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_spoofed_forwarded_for_cannot_bypass_the_limit(auth_client, fake_db):
    add_user(fake_db)
    for i in range(5):
        r = await auth_client.post(
            "/api/v1/auth/login",
            json={"email": VICTIM, "password": "bad"},
            headers={"X-Forwarded-For": f"10.9.8.{i}", "X-Real-IP": f"10.9.7.{i}"},
        )
        assert r.status_code == 401
    r = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": VICTIM, "password": "bad"},
        headers={"X-Forwarded-For": "10.1.1.1"},
    )
    assert r.status_code == 429  # rotating X-Forwarded-For created no fresh budget


@pytest.mark.anyio
async def test_without_a_trusted_header_address_scopes_are_skipped_and_xff_is_ignored(
    auth_client, fake_db, monkeypatch, caplog
):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", None)
    add_user(fake_db)
    with caplog.at_level(logging.WARNING, logger="app.rate_limit"):
        for i in range(6):
            r = await auth_client.post(
                "/api/v1/auth/login",
                json={"email": VICTIM, "password": "bad"},
                headers={"X-Forwarded-For": f"10.0.0.{i}"},
            )
            assert r.status_code == 401  # the 5-per-pair limit is NOT applied without an address
    assert fakes.count_for("login_pair") == 0 and fakes.count_for("login_ip") == 0
    assert fakes.count_for("login_account") == 6  # only the account ceiling counts
    assert "TRUSTED_CLIENT_IP_HEADER is not set" in caplog.text
    # The account ceiling (30) is still the backstop.
    for _ in range(24):
        await login(auth_client, VICTIM)
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 429


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["garbage", "1.2.3.4, 5.6.7.8", ""])
async def test_an_invalid_trusted_header_value_is_treated_as_unknown(auth_client, fake_db, value):
    add_user(fake_db)
    r = await auth_client.post(
        "/api/v1/auth/login", json={"email": VICTIM, "password": "bad"}, headers={IP_HEADER: value}
    )
    assert r.status_code == 401
    assert fakes.count_for("login_pair") == 0 and fakes.count_for("login_account") == 1


# ------------------------------------------------------------------------------
# Fail closed
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_login_fails_closed_with_503_when_the_limiter_is_unavailable(auth_client, fake_db):
    add_user(fake_db)
    fakes.set_failing(True)
    # Even the correct password is refused: no unlimited attempts while the limiter is down.
    response = await login(auth_client, VICTIM, GOOD)
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "RATE_LIMITER_UNAVAILABLE" and body["isRetryable"] is True
    assert "retry-after" not in response.headers  # an outage is not a rate-limit wait
    fakes.set_failing(False)
    assert (await login(auth_client, VICTIM, GOOD)).status_code == 200


# ------------------------------------------------------------------------------
# Signup / register / refresh
# ------------------------------------------------------------------------------


def signup_body(n: int) -> dict:
    return {"name": f"Person {n}", "email": f"person{n}@example.com", "password": "StrongPassword123!"}


@pytest.mark.anyio
async def test_signup_and_register_share_one_per_address_limit(auth_client):
    for n in range(3):
        assert (await auth_client.post("/api/v1/auth/signup", json=signup_body(n))).status_code == 201
    for n in range(3, 5):
        assert (await auth_client.post("/api/v1/auth/register", json=signup_body(n))).status_code == 201
    blocked = await auth_client.post("/api/v1/auth/signup", json=signup_body(5))
    assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert blocked.json()["isRetryable"] is True and 0 < int(blocked.headers["retry-after"]) <= 3600
    also = await auth_client.post("/api/v1/auth/register", json=signup_body(6))
    assert also.status_code == 429
    other = await auth_client.post(
        "/api/v1/auth/signup", json=signup_body(7), headers={IP_HEADER: "198.51.100.77"}
    )
    assert other.status_code == 201  # another address has its own budget


@pytest.mark.anyio
async def test_signup_keeps_its_existing_duplicate_email_response(auth_client):
    assert (await auth_client.post("/api/v1/auth/signup", json=signup_body(1))).status_code == 201
    dup = await auth_client.post("/api/v1/auth/signup", json=signup_body(1))
    assert dup.status_code == 409 and dup.json()["code"] == "EMAIL_ALREADY_EXISTS"


@pytest.mark.anyio
async def test_signup_and_refresh_fail_closed_with_503(auth_client, fake_db):
    fakes.set_failing(True)
    signup = await auth_client.post("/api/v1/auth/signup", json=signup_body(1))
    refresh = await auth_client.post("/api/v1/auth/refresh", json={"refreshToken": "x" * 40})
    for response in (signup, refresh):
        assert response.status_code == 503
        assert response.json()["code"] == "RATE_LIMITER_UNAVAILABLE"
    assert not any(u.email == "person1@example.com" for u in fake_db.users.values())  # not processed


@pytest.mark.anyio
async def test_signup_is_not_address_limited_without_a_trusted_header(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_CLIENT_IP_HEADER", None)
    for n in range(8):
        assert (await auth_client.post("/api/v1/auth/signup", json=signup_body(n))).status_code == 201


@pytest.mark.anyio
async def test_refresh_is_limited_per_address(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_REFRESH_IP_MAX", 3)
    for _ in range(3):
        r = await auth_client.post("/api/v1/auth/refresh", json={"refreshToken": "x" * 40})
        assert r.status_code == 401  # invalid token, but counted
    blocked = await auth_client.post("/api/v1/auth/refresh", json={"refreshToken": "x" * 40})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert blocked.json()["isRetryable"] is True


# ------------------------------------------------------------------------------
# CORS and mobile (bearer, no Origin, no CSRF token) compatibility
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_retry_after_is_exposed_to_browser_clients_through_cors(auth_client, fake_db):
    add_user(fake_db)
    origin = settings.CORS_ORIGINS[0]
    for _ in range(5):
        await login(auth_client, VICTIM)
    blocked = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": VICTIM, "password": "bad"},
        headers={"Origin": origin},
    )
    assert blocked.status_code == 429
    assert blocked.headers["access-control-allow-origin"] == origin
    assert "retry-after" in blocked.headers["access-control-expose-headers"].lower()


@pytest.mark.anyio
async def test_mobile_style_bearer_requests_need_no_origin_cookie_or_csrf_token(auth_client, fake_db):
    add_user(fake_db)
    logged_in = await login(auth_client, VICTIM, GOOD)  # no Origin, no cookie, no CSRF header
    assert logged_in.status_code == 200
    tokens = logged_in.json()["tokens"]
    assert "set-cookie" not in logged_in.headers  # authentication stays bearer-only
    me = await auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['accessToken']}"}
    )
    assert me.status_code == 200 and me.json()["email"] == VICTIM
    refreshed = await auth_client.post("/api/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert refreshed.status_code == 200 and "set-cookie" not in refreshed.headers
