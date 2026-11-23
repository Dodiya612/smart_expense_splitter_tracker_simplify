"""T-50 change password on a real PostgreSQL database.

Verifies what the in-memory fakes in tests/test_change_password.py cannot: the
SELECT ... FOR UPDATE / ORM flush path, users.token_version, refresh-token revocation
rows, the password_changed CHECK constraint on notifications, and that an explicit "off"
preference row cannot silence the security notice.

SKIPPED when no local PostgreSQL is reachable (same rules and COINSCIOUS_TEST_PG_URL
setting as tests/test_transaction_integrity_pg.py: localhost only, never Supabase).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import hash_password, verify_password
from app.main import app
from app.models.notification import Notification, NotificationPreference
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import notifications
from app.services.notifications import _persist as real_persist
from tests.test_transaction_integrity_pg import pg  # noqa: F401 - pg is a fixture

OLD = "Password123!"
NEW = "Monsoon-Chai-4-Two!"


@pytest.fixture
async def world(pg, monkeypatch) -> AsyncIterator[dict[str, Any]]:  # noqa: F811
    monkeypatch.setattr(notifications, "_persist", real_persist)
    monkeypatch.setattr(notifications, "AsyncSessionLocal", pg["sessions"])
    user = User(id=uuid.uuid4(), email="meera@example.in", name="Meera Iyer",
                hashed_password=hash_password(OLD), is_active=True)
    async with pg["sessions"]() as s:
        s.add(user)
        await s.flush()
        # An explicit "off" row must not silence a security notice.
        s.add(NotificationPreference(user_id=user.id, kind="password_changed", enabled=False))
        await s.commit()

    async def override_get_db() -> AsyncIterator[Any]:
        async with pg["sessions"]() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield {**pg, "user": user, "client": client}
    app.dependency_overrides.clear()


async def _login(client: AsyncClient, device: str, password: str = OLD) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={
        "email": "meera@example.in", "password": password, "device_label": device})
    assert res.status_code == 200, res.text
    return res.json()["tokens"]


async def test_change_password_end_to_end_on_postgres(world):
    client: AsyncClient = world["client"]
    phone = await _login(client, "Phone")
    laptop = await _login(client, "Laptop")

    res = await client.post(
        "/api/v1/auth/change-password",
        json={"currentPassword": OLD, "newPassword": NEW, "confirmNewPassword": NEW},
        headers={"Authorization": f"Bearer {phone['accessToken']}"},
    )
    assert res.status_code == 200, res.text
    fresh = res.json()["tokens"]
    assert res.json()["revokedSessions"] == 1

    async with world["sessions"]() as s:
        user = (await s.execute(select(User).where(User.id == world["user"].id))).scalar_one()
        assert user.token_version == 1
        assert verify_password(NEW, user.hashed_password)
        live = (await s.execute(select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)))).scalars().all()
        assert len(live) == 1 and live[0].device_label == "Phone"
        notices = (await s.execute(select(Notification).where(
            Notification.user_id == user.id))).scalars().all()
        assert [n.kind for n in notices] == ["password_changed"]

    laptop_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {laptop['accessToken']}"})
    assert laptop_me.status_code == 401
    laptop_refresh = await client.post("/api/v1/auth/refresh", json={"refreshToken": laptop["refreshToken"]})
    assert laptop_refresh.status_code == 401
    phone_me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fresh['accessToken']}"})
    assert phone_me.status_code == 200


async def test_wrong_current_password_writes_nothing_on_postgres(world):
    client: AsyncClient = world["client"]
    phone = await _login(client, "Phone")
    res = await client.post(
        "/api/v1/auth/change-password",
        json={"currentPassword": "wrong-Password-99", "newPassword": NEW, "confirmNewPassword": NEW},
        headers={"Authorization": f"Bearer {phone['accessToken']}"},
    )
    assert res.status_code == 400
    async with world["sessions"]() as s:
        user = (await s.execute(select(User).where(User.id == world["user"].id))).scalar_one()
        assert user.token_version == 0
        assert verify_password(OLD, user.hashed_password)
        revoked = (await s.execute(select(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(True)))).scalars().all()
        assert revoked == []
        assert (await s.execute(select(Notification))).scalars().all() == []


# ---- T-50 race: login / refresh concurrent with a password change ------------------------
#
# A password change holds FOR UPDATE on the user row for its whole transaction. Login and
# refresh take FOR SHARE on that row first, so they must WAIT and then observe the change.
# The held lock below stands in for an in-flight change-password transaction.


async def _hold_change(world, *, new_hash: str):
    """Open a transaction that locks the user like change-password does; returns a commit fn."""

    from sqlalchemy import text, update

    session = world["sessions"]()
    await session.execute(
        text("SELECT 1 FROM users WHERE id = :id FOR UPDATE"), {"id": world["user"].id}
    )

    async def commit() -> None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == world["user"].id, RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        await session.execute(
            update(User).where(User.id == world["user"].id).values(
                hashed_password=new_hash, token_version=User.token_version + 1
            )
        )
        await session.commit()
        await session.close()

    return commit


async def test_refresh_waits_for_an_in_flight_password_change_then_fails(world):
    import asyncio

    client: AsyncClient = world["client"]
    laptop = await _login(client, "Laptop")
    commit = await _hold_change(world, new_hash=hash_password(NEW))

    pending = asyncio.create_task(
        client.post("/api/v1/auth/refresh", json={"refreshToken": laptop["refreshToken"]})
    )
    await asyncio.sleep(0.5)
    assert not pending.done(), "refresh must wait for the user-row lock"
    await commit()
    res = await asyncio.wait_for(pending, timeout=10)
    assert res.status_code == 401
    async with world["sessions"]() as s:
        live = (await s.execute(select(RefreshToken).where(
            RefreshToken.user_id == world["user"].id, RefreshToken.is_revoked.is_(False)))).scalars().all()
        assert live == []


async def test_login_with_old_password_waits_for_an_in_flight_change_then_fails(world):
    import asyncio

    client: AsyncClient = world["client"]
    commit = await _hold_change(world, new_hash=hash_password(NEW))
    pending = asyncio.create_task(client.post("/api/v1/auth/login", json={
        "email": "meera@example.in", "password": OLD, "device_label": "Attacker"}))
    await asyncio.sleep(0.5)
    assert not pending.done(), "login must wait for the user-row lock"
    await commit()
    res = await asyncio.wait_for(pending, timeout=10)
    assert res.status_code == 401
    async with world["sessions"]() as s:
        live = (await s.execute(select(RefreshToken).where(
            RefreshToken.user_id == world["user"].id, RefreshToken.is_revoked.is_(False)))).scalars().all()
        assert live == []
