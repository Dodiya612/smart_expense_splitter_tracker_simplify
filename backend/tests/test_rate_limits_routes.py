"""Rate limits on invitation and group-join routes (T-39).

Reuses the in-memory group fixtures from tests/test_groups.py. Limits are lowered with
monkeypatch so each test needs only a few requests; the defaults are checked in
tests/test_rate_limiter.py. Existing invitation error codes must be unchanged.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.config import settings
from tests import rate_limit_fakes as fakes
from tests import test_groups as groups

group_db = groups.group_db
user_owner = groups.user_owner
user_member = groups.user_member
user_stranger = groups.user_stranger
client = groups.client
auth_headers = groups.auth_headers


async def make_group(client, owner) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/groups", json={"name": "Flat 301", "type": "flat"}, headers=auth_headers(owner)
    )
    return resp.json()["id"], resp.json()["joinCode"]


def assert_rate_limited(response) -> None:
    assert response.status_code == 429, response.text
    body = response.json()
    assert body["code"] == "RATE_LIMIT_EXCEEDED" and body["isRetryable"] is True
    assert int(response.headers["retry-after"]) > 0


# ------------------------------------------------------------------------------
# POST /groups/join (join-code guessing)
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_join_by_code_is_limited_per_user_and_keeps_its_error_codes(
    client, user_owner, user_member, user_stranger, monkeypatch
):
    monkeypatch.setattr(settings, "RATE_LIMIT_JOIN_USER_MAX", 2)
    for _ in range(2):
        r = await client.post("/api/v1/groups/join", json={"code": "WRONGCODE"}, headers=auth_headers(user_member))
        assert r.status_code == 400 and r.json()["code"] == "INVALID_JOIN_CODE"  # unchanged
    assert_rate_limited(
        await client.post("/api/v1/groups/join", json={"code": "WRONGCODE"}, headers=auth_headers(user_member))
    )
    # Someone else is not affected, and a valid code still works for them.
    _, code = await make_group(client, user_owner)
    ok = await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_stranger))
    assert ok.status_code == 200


@pytest.mark.anyio
async def test_a_guessing_user_is_stopped_before_they_can_try_the_real_code(
    client, user_owner, user_member, monkeypatch
):
    monkeypatch.setattr(settings, "RATE_LIMIT_JOIN_USER_MAX", 3)
    _, code = await make_group(client, user_owner)
    for _ in range(3):
        await client.post("/api/v1/groups/join", json={"code": "GUESS123"}, headers=auth_headers(user_member))
    blocked = await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    assert_rate_limited(blocked)  # even the right code is refused until the window ends
    fakes.advance(900)
    assert (
        await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    ).status_code == 200


# ------------------------------------------------------------------------------
# POST /groups/{id}/invitations and /join-code
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_creating_invitations_is_limited_per_user(client, user_owner, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_INVITE_USER_MAX", 2)
    group_id, _ = await make_group(client, user_owner)
    url = f"/api/v1/groups/{group_id}/invitations"
    for n in range(2):
        r = await client.post(url, json={"email": f"guest{n}@example.com"}, headers=auth_headers(user_owner))
        assert r.status_code == 201
    assert_rate_limited(await client.post(url, json={"email": "guest9@example.com"}, headers=auth_headers(user_owner)))


@pytest.mark.anyio
async def test_invitation_error_codes_are_unchanged_below_the_limit(client, user_owner, user_member):
    group_id, code = await make_group(client, user_owner)
    url = f"/api/v1/groups/{group_id}/invitations"
    first = await client.post(url, json={"userId": str(user_member.id)}, headers=auth_headers(user_owner))
    assert first.status_code == 201
    again = await client.post(url, json={"userId": str(user_member.id)}, headers=auth_headers(user_owner))
    assert again.status_code == 409 and again.json()["code"] == "INVITATION_ALREADY_EXISTS"
    await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    member = await client.post(url, json={"userId": str(user_member.id)}, headers=auth_headers(user_owner))
    assert member.status_code == 409 and member.json()["code"] == "ALREADY_MEMBER"


@pytest.mark.anyio
async def test_rotating_the_join_code_is_limited_per_user(client, user_owner, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_JOIN_CODE_USER_MAX", 2)
    group_id, _ = await make_group(client, user_owner)
    url = f"/api/v1/groups/{group_id}/join-code"
    for _ in range(2):
        assert (await client.post(url, headers=auth_headers(user_owner))).status_code == 201
    assert_rate_limited(await client.post(url, headers=auth_headers(user_owner)))


# ------------------------------------------------------------------------------
# Accept / decline
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_accept_and_decline_share_a_per_user_limit(client, user_owner, user_member, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_INVITE_RESPOND_USER_MAX", 2)
    group_id, _ = await make_group(client, user_owner)
    inv = (
        await client.post(
            f"/api/v1/groups/{group_id}/invitations",
            json={"userId": str(user_member.id)},
            headers=auth_headers(user_owner),
        )
    ).json()
    first = await client.post(f"/api/v1/invitations/{inv['id']}/decline", headers=auth_headers(user_member))
    assert first.status_code == 204
    again = await client.post(f"/api/v1/invitations/{inv['id']}/accept", headers=auth_headers(user_member))
    assert again.status_code == 400 and again.json()["code"] == "INVALID_INVITATION_STATUS"  # unchanged
    assert_rate_limited(
        await client.post(f"/api/v1/invitations/{inv['id']}/accept", headers=auth_headers(user_member))
    )


# ------------------------------------------------------------------------------
# Authentication first, per-user isolation, failure policy
# ------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unauthenticated_requests_get_401_and_spend_no_budget(client):
    for _ in range(3):
        r = await client.post("/api/v1/groups/join", json={"code": "WRONGCODE"})
        assert r.status_code in (401, 403)
    assert fakes.scopes() == set()


@pytest.mark.anyio
async def test_one_users_limit_never_blocks_another_user(client, user_owner, user_member, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_JOIN_USER_MAX", 1)
    await client.post("/api/v1/groups/join", json={"code": "WRONGCODE"}, headers=auth_headers(user_member))
    assert_rate_limited(
        await client.post("/api/v1/groups/join", json={"code": "WRONGCODE"}, headers=auth_headers(user_member))
    )
    other = await client.post("/api/v1/groups/join", json={"code": "WRONGCODE"}, headers=auth_headers(user_owner))
    assert other.status_code == 400  # reached the handler, not the limiter


def assert_unavailable(response) -> None:
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "RATE_LIMITER_UNAVAILABLE" and body["isRetryable"] is True
    assert "retry-after" not in response.headers  # an outage is not a rate-limit wait


@pytest.mark.anyio
async def test_creating_an_invitation_fails_closed_and_creates_nothing(client, user_owner, group_db):
    group_id, _ = await make_group(client, user_owner)
    fakes.set_failing(True)
    r = await client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"email": f"{uuid.uuid4().hex[:6]}@example.com"},
        headers=auth_headers(user_owner),
    )
    assert_unavailable(r)
    # Creating the group stored its join-code row; no e-mail invitation was created.
    assert not any(i.invited_email for i in group_db.invitations.values())
    fakes.set_failing(False)  # back to normal: the same request now succeeds
    ok = await client.post(
        f"/api/v1/groups/{group_id}/invitations", json={"email": "later@example.com"},
        headers=auth_headers(user_owner),
    )
    assert ok.status_code == 201


@pytest.mark.anyio
async def test_join_by_code_fails_closed_and_does_not_join(client, user_owner, user_member, group_db):
    group_id, code = await make_group(client, user_owner)
    fakes.set_failing(True)
    assert_unavailable(
        await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    )
    assert (uuid.UUID(group_id), user_member.id) not in group_db.group_members


@pytest.mark.anyio
async def test_join_code_rotation_fails_closed_and_does_not_rotate(client, user_owner):
    group_id, _ = await make_group(client, user_owner)
    fakes.set_failing(True)
    assert_unavailable(
        await client.post(f"/api/v1/groups/{group_id}/join-code", headers=auth_headers(user_owner))
    )


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["accept", "decline"])
async def test_accept_and_decline_fail_closed_and_leave_the_invitation_pending(
    client, user_owner, user_member, group_db, action
):
    group_id, _ = await make_group(client, user_owner)
    inv = (
        await client.post(
            f"/api/v1/groups/{group_id}/invitations",
            json={"userId": str(user_member.id)},
            headers=auth_headers(user_owner),
        )
    ).json()
    fakes.set_failing(True)
    assert_unavailable(
        await client.post(f"/api/v1/invitations/{inv['id']}/{action}", headers=auth_headers(user_member))
    )
    assert group_db.invitations[uuid.UUID(inv["id"])].status == "pending"


@pytest.mark.anyio
async def test_no_user_scoped_request_bypasses_its_limit_during_an_outage(client, user_owner, monkeypatch):
    """With the limit at 1, an outage must not let extra requests through as 201."""
    monkeypatch.setattr(settings, "RATE_LIMIT_INVITE_USER_MAX", 1)
    group_id, _ = await make_group(client, user_owner)
    url = f"/api/v1/groups/{group_id}/invitations"
    assert (await client.post(url, json={"email": "a@example.com"}, headers=auth_headers(user_owner))).status_code == 201
    fakes.set_failing(True)
    for n in range(3):
        r = await client.post(url, json={"email": f"b{n}@example.com"}, headers=auth_headers(user_owner))
        assert r.status_code == 503
