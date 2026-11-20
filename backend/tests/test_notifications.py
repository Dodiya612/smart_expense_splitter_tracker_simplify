"""Notification centre (US-38 / T-36): service rules and group / invitation events.

Runs against the in-memory fake store (tests/notification_fakes.py). The database
guarantees (ON CONFLICT dedupe, concurrency, preferences, endpoint isolation) are
covered on a real PostgreSQL in tests/test_notifications_pg.py.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.notifications import _decode_cursor
from app.models import notification as notification_models
from app.schemas.notification import NotificationPreferencesUpdateRequest
from app.services import notifications
from tests import notification_fakes as fakes
from tests import test_groups as groups

# Re-use the group fixtures (fake DB, users, client).
group_db = groups.group_db
user_owner = groups.user_owner
user_member = groups.user_member
user_stranger = groups.user_stranger
client = groups.client
auth_headers = groups.auth_headers

U1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
U2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
U3 = uuid.UUID("33333333-3333-3333-3333-333333333333")


# ==============================================================================
# Service rules
# ==============================================================================


@pytest.mark.asyncio
async def test_notify_users_excludes_actor_and_duplicates():
    sent = await notifications.notify_users(
        [U1, U2, U2, U3], U1, "member_joined", "ref-1", {"group_name": "Flat"}
    )
    assert {e.user_id for e in sent} == {str(U2), str(U3)}
    assert all(e.payload["actor_id"] == str(U1) for e in sent)
    assert all(e.dedupe_key == f"member_joined:ref-1:{e.user_id}" for e in sent)


@pytest.mark.asyncio
async def test_same_event_never_notifies_the_same_user_twice():
    first = await notifications.notify_users([U2], U1, "settlement_recorded", "s-1")
    again = await notifications.notify_users([U2], U1, "settlement_recorded", "s-1")
    assert len(first) == 1
    assert again == []
    assert len(fakes.get_emitted_notifications()) == 1


@pytest.mark.asyncio
async def test_new_version_in_ref_notifies_again():
    await notifications.notify_users([U2], U1, "group_expense_updated", "e-1:v2")
    await notifications.notify_users([U2], U1, "group_expense_updated", "e-1:v3")
    await notifications.notify_users([U2], U1, "group_expense_updated", "e-1:v3")
    assert len(fakes.get_emitted_notifications()) == 2


@pytest.mark.asyncio
async def test_emit_stores_title_body_and_group():
    gid = uuid.uuid4()
    ok = await notifications.emit(
        U2, "group_expense_created", "e-9", "group_expense_created:e-9:u2",
        {"group_name": "Flat", "actor_name": "Alex", "description": "Dinner", "amount_paise": 150050},
        group_id=gid,
    )
    assert ok is True
    (event,) = fakes.get_emitted_notifications()
    assert event.title == "New expense in Flat"
    assert event.body == "Alex added Dinner (₹1,500.50)."
    assert event.group_id == str(gid)


@pytest.mark.asyncio
async def test_switched_off_kind_is_not_stored_but_other_kinds_are():
    fakes.disable_kind(U2, "member_joined")
    sent = await notifications.notify_users([U2, U3], U1, "member_joined", "r")
    assert {e.user_id for e in sent} == {str(U3)}
    other = await notifications.notify_users([U2], U1, "member_left", "r")
    assert len(other) == 1


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected_without_raising():
    assert await notifications.emit(U2, "not_a_kind", "r", "k") is False
    assert await notifications.notify_users([U2], U1, "not_a_kind", "r") == []
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_storage_failure_is_logged_and_swallowed(monkeypatch, caplog):
    async def broken(_events: Any) -> Any:
        raise RuntimeError("database down")

    monkeypatch.setattr(notifications, "_persist", broken)
    with caplog.at_level("ERROR", logger="app.notifications"):
        assert await notifications.emit(U2, "member_left", "r", "k") is False
        assert await notifications.notify_users([U2], U1, "member_left", "r") == []
    assert "Notification delivery failed" in caplog.text


def test_every_kind_renders_a_title_and_body():
    for kind in notification_models.NOTIFICATION_KINDS:
        title, body = notifications.render_notification(
            kind, {"group_name": "Flat", "actor_name": "Alex", "target_name": "Bo"}
        )
        assert title != "Notification" and body


def test_migration_and_model_agree_on_kinds():
    import importlib.util
    from pathlib import Path

    versions = Path(__file__).resolve().parent.parent / "alembic" / "versions"

    def load(name: str, filename: str):
        spec = importlib.util.spec_from_file_location(name, versions / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    m011 = load("m011", "011_create_notifications.py")
    m014 = load("m014", "014_password_change.py")
    m015 = load("m015", "015_recurring_expenses.py")
    assert m011.down_revision == "010_create_settlements"
    # 014 (T-50) replaces 011's CHECK constraints: it must start from 011's list.
    assert tuple(m014.OLD_KINDS) == tuple(m011.KINDS)
    assert m014.down_revision == "013_merge_rate_limit_and_receipts"
    # 015 (T-44) replaces 014's: it must start from 014's list and end at the model's.
    assert tuple(m015.OLD_KINDS) == tuple(m014.NEW_KINDS)
    assert tuple(m015.NEW_KINDS) == notification_models.NOTIFICATION_KINDS
    assert m015.down_revision == "014_password_change"


# ==============================================================================
# Preference and cursor validation
# ==============================================================================


def test_preference_update_rejects_unknown_and_duplicate_kinds():
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdateRequest(preferences=[{"kind": "nope", "enabled": False}])
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdateRequest(
            preferences=[{"kind": "member_left", "enabled": False}, {"kind": "member_left", "enabled": True}]
        )
    ok = NotificationPreferencesUpdateRequest(preferences=[{"kind": "member_left", "enabled": False}])
    assert ok.preferences[0].enabled is False


def test_security_kinds_cannot_be_switched_off(monkeypatch):
    monkeypatch.setattr("app.schemas.notification.SECURITY_KINDS", frozenset({"member_removed"}))
    with pytest.raises(ValidationError):
        NotificationPreferencesUpdateRequest(preferences=[{"kind": "member_removed", "enabled": False}])
    NotificationPreferencesUpdateRequest(preferences=[{"kind": "member_removed", "enabled": True}])


def test_bad_cursor_is_a_400():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _decode_cursor("not-a-cursor")
    assert exc.value.status_code == 400


# ==============================================================================
# Group and invitation events
# ==============================================================================


async def _create_group(client, owner) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/groups", json={"name": "Flat 301", "type": "flat"}, headers=auth_headers(owner)
    )
    return resp.json()["id"], resp.json()["joinCode"]


def _by_kind(kind: str):
    return [n for n in fakes.get_emitted_notifications() if n.kind == kind]


@pytest.mark.asyncio
async def test_member_joined_notifies_existing_members_not_the_joiner(client, user_owner, user_member):
    _, code = await _create_group(client, user_owner)
    resp = await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    assert resp.status_code == 200
    sent = _by_kind("member_joined")
    assert [n.user_id for n in sent] == [str(user_owner.id)]
    assert sent[0].title == "New member in Flat 301"


@pytest.mark.asyncio
async def test_failed_join_sends_nothing(client, user_owner, user_member):
    _, code = await _create_group(client, user_owner)
    resp = await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_owner))
    assert resp.status_code == 409
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_invitation_received_goes_to_the_registered_invitee_only(client, user_owner, user_member):
    group_id, _ = await _create_group(client, user_owner)
    resp = await client.post(
        f"/api/v1/groups/{group_id}/invitations", json={"userId": str(user_member.id)},
        headers=auth_headers(user_owner),
    )
    assert resp.status_code == 201
    sent = _by_kind("invitation_received")
    assert [n.user_id for n in sent] == [str(user_member.id)]
    assert sent[0].payload["invitation_id"] == resp.json()["id"]


@pytest.mark.asyncio
async def test_invitation_to_unregistered_email_notifies_nobody(client, user_owner):
    group_id, _ = await _create_group(client, user_owner)
    resp = await client.post(
        f"/api/v1/groups/{group_id}/invitations", json={"email": "nobody@example.com"},
        headers=auth_headers(user_owner),
    )
    assert resp.status_code == 201
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_accept_notifies_inviter_once_without_a_second_joined_notice(client, user_owner, user_member):
    group_id, _ = await _create_group(client, user_owner)
    inv = (
        await client.post(
            f"/api/v1/groups/{group_id}/invitations", json={"userId": str(user_member.id)},
            headers=auth_headers(user_owner),
        )
    ).json()
    resp = await client.post(f"/api/v1/invitations/{inv['id']}/accept", headers=auth_headers(user_member))
    assert resp.status_code == 200
    accepted = _by_kind("invitation_accepted")
    assert [n.user_id for n in accepted] == [str(user_owner.id)]
    assert _by_kind("member_joined") == []  # the only other member is the inviter

    again = await client.post(f"/api/v1/invitations/{inv['id']}/accept", headers=auth_headers(user_member))
    assert again.status_code == 400
    assert len(_by_kind("invitation_accepted")) == 1


@pytest.mark.asyncio
async def test_decline_notifies_the_inviter(client, user_owner, user_member):
    group_id, _ = await _create_group(client, user_owner)
    inv = (
        await client.post(
            f"/api/v1/groups/{group_id}/invitations", json={"userId": str(user_member.id)},
            headers=auth_headers(user_owner),
        )
    ).json()
    resp = await client.post(f"/api/v1/invitations/{inv['id']}/decline", headers=auth_headers(user_member))
    assert resp.status_code == 204
    assert [n.user_id for n in _by_kind("invitation_declined")] == [str(user_owner.id)]


@pytest.mark.asyncio
async def test_removed_member_is_told_and_the_actor_is_not(client, user_owner, user_member):
    group_id, code = await _create_group(client, user_owner)
    await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    fakes.clear_emitted_notifications()

    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}", headers=auth_headers(user_owner)
    )
    assert resp.status_code == 204
    sent = _by_kind("member_removed")
    # The owner is the actor and the only admin, so just the removed member hears about it.
    assert [n.user_id for n in sent] == [str(user_member.id)]
    assert sent[0].payload["you"] is True
    assert sent[0].title == "Removed from Flat 301"


@pytest.mark.asyncio
async def test_leaving_notifies_admins_not_the_leaver(client, user_owner, user_member):
    group_id, code = await _create_group(client, user_owner)
    await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    fakes.clear_emitted_notifications()

    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}", headers=auth_headers(user_member)
    )
    assert resp.status_code == 204
    assert [n.user_id for n in _by_kind("member_left")] == [str(user_owner.id)]


@pytest.mark.asyncio
async def test_forbidden_removal_sends_nothing(client, user_owner, user_member, user_stranger):
    group_id, code = await _create_group(client, user_owner)
    await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    fakes.clear_emitted_notifications()
    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}", headers=auth_headers(user_stranger)
    )
    assert resp.status_code in (403, 404)
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_notification_failure_after_a_join_does_not_fail_the_join(
    client, user_owner, user_member, monkeypatch
):
    async def broken(_events: Any) -> Any:
        raise RuntimeError("database down")

    _, code = await _create_group(client, user_owner)
    monkeypatch.setattr(notifications, "_persist", broken)
    resp = await client.post("/api/v1/groups/join", json={"code": code}, headers=auth_headers(user_member))
    assert resp.status_code == 200


# ==============================================================================
# Recipient-id hardening and logging (T-36 review fix)
# ==============================================================================

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.services.notifications import NotificationEvent  # noqa: E402
from app.services.notifications import _persist as real_persist  # noqa: E402


class _StubResult:
    def all(self) -> list[Any]:
        return []

    def scalar_one_or_none(self) -> Any:
        return uuid.uuid4()


class _StubNested:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> bool:
        return False  # propagate, like a real savepoint after rolling back


class _StubSession:
    """Just enough AsyncSession for _persist: records inserts, can fail for one user."""

    def __init__(self, fail_user: uuid.UUID | None = None) -> None:
        self.inserted: list[uuid.UUID] = []
        self.committed = False
        self.fail_user = fail_user

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def begin_nested(self) -> _StubNested:
        return _StubNested()

    async def commit(self) -> None:
        self.committed = True

    async def execute(self, stmt: Any) -> _StubResult:
        if getattr(stmt, "is_insert", False):
            user_id = stmt.compile(dialect=postgresql.dialect()).params["user_id"]
            if user_id == self.fail_user:
                # Real SQLAlchemy errors embed the statement parameters (title, body, payload).
                raise RuntimeError("insert failed [parameters: SECRET-PAYLOAD-TEXT]")
            self.inserted.append(user_id)
        return _StubResult()


def _event(user: str, group: str | None = None) -> NotificationEvent:
    return NotificationEvent(
        user_id=user, kind="member_left", ref="r", dedupe_key=f"member_left:r:{user}",
        payload={"secret": "SECRET-PAYLOAD-TEXT"}, group_id=group, title="t", body="b",
    )


@pytest.mark.asyncio
async def test_notify_users_skips_invalid_recipients_and_notifies_the_valid_ones():
    sent = await notifications.notify_users([U2, "not-a-uuid", None, U3], U1, "member_left", "r")
    assert {e.user_id for e in sent} == {str(U2), str(U3)}


@pytest.mark.asyncio
async def test_emit_with_an_invalid_recipient_returns_false_without_raising():
    assert await notifications.emit("nope", "member_left", "r", "k") is False
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_persist_skips_invalid_ids_and_still_stores_valid_ones(monkeypatch, caplog):
    session = _StubSession()
    monkeypatch.setattr(notifications, "AsyncSessionLocal", lambda: session)
    events = [_event("garbage"), _event(str(U2)), _event(str(U3), group="also-garbage"), _event(str(U3))]
    with caplog.at_level("ERROR", logger="app.notifications"):
        stored = await real_persist(events)
    assert session.inserted == [U2, U3]
    assert [e.user_id for e in stored] == [str(U2), str(U3)]
    assert session.committed is True
    assert "invalid recipient or group id" in caplog.text


@pytest.mark.asyncio
async def test_persist_with_only_invalid_ids_never_opens_a_session(monkeypatch):
    def boom() -> Any:
        raise AssertionError("no session should be opened")

    monkeypatch.setattr(notifications, "AsyncSessionLocal", boom)
    assert await real_persist([_event("garbage")]) == []


@pytest.mark.asyncio
async def test_one_failing_recipient_does_not_block_others_and_logs_no_payload(monkeypatch, caplog):
    session = _StubSession(fail_user=U2)
    monkeypatch.setattr(notifications, "AsyncSessionLocal", lambda: session)
    with caplog.at_level("DEBUG", logger="app.notifications"):
        stored = await real_persist([_event(str(U2)), _event(str(U3))])
    assert [e.user_id for e in stored] == [str(U3)]
    assert session.committed is True
    error_text = " ".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")
    assert "Notification insert failed" in error_text and "RuntimeError" in error_text
    assert "SECRET-PAYLOAD-TEXT" not in error_text  # parameters never reach the ERROR log
