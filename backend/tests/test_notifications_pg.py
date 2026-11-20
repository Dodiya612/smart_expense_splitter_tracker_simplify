"""Real-PostgreSQL checks for the notification centre (US-38 / T-36).

Verifies what the in-memory fakes cannot: the unique (user_id, dedupe_key)
constraint with ON CONFLICT DO NOTHING under concurrency, preferences, per-user
isolation through the real endpoints, and that a transaction killed before COMMIT
produces no notification.

SKIPPED when no local PostgreSQL is reachable (same rules and COINSCIOUS_TEST_PG_URL
setting as tests/test_transaction_integrity_pg.py: localhost only, never Supabase).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import MissingGreenlet, SQLAlchemyError

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.notification import Notification, NotificationPreference
from app.schemas.shared_expense import SharedExpenseCreateRequest
from app.services import notifications, shared_expense_service
from app.services.notifications import _persist as real_persist
from app.services.notifications import active_member_roles as real_active_member_roles
from tests.test_transaction_integrity_pg import (  # noqa: F401 - pg is a fixture
    count,
    kill_connection_before_commit,
    pg,
    seed,
)


@pytest.fixture
async def real_store(pg, monkeypatch) -> AsyncIterator[dict[str, Any]]:
    """Point the real notification store at the throwaway database."""
    monkeypatch.setattr(notifications, "_persist", real_persist)
    monkeypatch.setattr(notifications, "active_member_roles", real_active_member_roles)
    monkeypatch.setattr(notifications, "AsyncSessionLocal", pg["sessions"])
    world = await seed(pg["sessions"])
    yield {**pg, "world": world}


def bearer(user: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, email=user.email)}"}


@pytest.fixture
async def api(real_store) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[Any]:
        async with real_store["sessions"]() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def rows_for(real_store: dict[str, Any], user_id: uuid.UUID) -> list[Notification]:
    async with real_store["sessions"]() as s:
        result = await s.execute(select(Notification).where(Notification.user_id == user_id))
        return list(result.scalars().all())


async def test_notification_is_persisted_with_type_message_time_and_unread(real_store):
    alex, blair, _ = real_store["world"]["users"]
    group = real_store["world"]["group"]
    sent = await notifications.notify_users(
        [alex.id, blair.id], alex.id, "member_joined", "r-1",
        {"group_name": "Flat", "actor_name": "Alex"}, group_id=group.id,
    )
    assert len(sent) == 1
    (row,) = await rows_for(real_store, blair.id)
    assert row.kind == "member_joined"
    assert row.title == "New member in Flat"
    assert row.body == "Alex joined the group."
    assert row.read_at is None and row.created_at is not None
    assert row.group_id == group.id
    assert await rows_for(real_store, alex.id) == []  # the actor is never notified


async def test_same_event_twice_stores_one_row(real_store):
    alex, blair, _ = real_store["world"]["users"]
    await notifications.notify_users([blair.id], alex.id, "settlement_recorded", "s-1")
    again = await notifications.notify_users([blair.id], alex.id, "settlement_recorded", "s-1")
    assert again == []
    assert len(await rows_for(real_store, blair.id)) == 1


async def test_concurrent_duplicate_inserts_store_exactly_one_row(real_store):
    alex, blair, _ = real_store["world"]["users"]
    results = await asyncio.gather(
        *[
            notifications.emit(blair.id, "member_left", "r-1", "member_left:r-1:blair", {})
            for _ in range(25)
        ]
    )
    assert sum(1 for r in results if r) == 1
    assert len(await rows_for(real_store, blair.id)) == 1


async def test_database_rejects_a_duplicate_even_when_the_app_check_is_bypassed(real_store):
    alex, blair, _ = real_store["world"]["users"]
    values = dict(user_id=blair.id, kind="member_left", title="t", body="b", dedupe_key="dup")
    async with real_store["sessions"]() as s:
        s.add(Notification(**values))
        await s.commit()
    async with real_store["sessions"]() as s:
        s.add(Notification(**values))
        with pytest.raises(SQLAlchemyError):
            await s.commit()


async def test_database_rejects_unknown_kind(real_store):
    _, blair, _ = real_store["world"]["users"]
    async with real_store["sessions"]() as s:
        s.add(Notification(user_id=blair.id, kind="bogus", title="t", body="b", dedupe_key="k"))
        with pytest.raises(SQLAlchemyError):
            await s.commit()


async def test_disabled_preference_stores_nothing_and_missing_preference_means_enabled(real_store):
    alex, blair, casey = real_store["world"]["users"]
    async with real_store["sessions"]() as s:
        s.add(NotificationPreference(user_id=blair.id, kind="member_joined", enabled=False))
        await s.commit()
    sent = await notifications.notify_users([blair.id, casey.id], alex.id, "member_joined", "r-2")
    assert {e.user_id for e in sent} == {str(casey.id)}
    assert await rows_for(real_store, blair.id) == []
    # Other kinds for the same user are unaffected.
    assert len(await notifications.notify_users([blair.id], alex.id, "member_left", "r-2")) == 1


async def test_one_bad_recipient_does_not_block_the_others(real_store):
    alex, blair, _ = real_store["world"]["users"]
    ghost = uuid.uuid4()  # not a user: violates the foreign key
    sent = await notifications.notify_users([ghost, blair.id], alex.id, "member_left", "r-3")
    assert {e.user_id for e in sent} == {str(blair.id)}


async def test_killed_transaction_creates_no_notification(real_store):
    alex = real_store["world"]["users"][0]
    payload = SharedExpenseCreateRequest(
        amount_paise=300000, description="Killed", category_id=real_store["world"]["category"].id
    )
    seen: dict[str, Any] = {}
    async with real_store["sessions"]() as s:
        kill_connection_before_commit(s, real_store["admin"], seen)
        with pytest.raises(SQLAlchemyError):
            await shared_expense_service.create_shared_expense(
                s, real_store["world"]["group"].id, alex, payload
            )
    assert seen.get("killed") is True
    assert await count(real_store["sessions"], select(func.count()).select_from(Notification)) == 0


async def test_committed_expense_creates_notifications_for_other_members_only(real_store):
    alex, blair, casey = real_store["world"]["users"]
    payload = SharedExpenseCreateRequest(
        amount_paise=300000, description="Groceries", category_id=real_store["world"]["category"].id
    )
    async with real_store["sessions"]() as s:
        try:
            await shared_expense_service.create_shared_expense(
                s, real_store["world"]["group"].id, alex, payload
            )
        except MissingGreenlet:
            # Existing bug, not T-36: after the commit and the notifications,
            # create_shared_expense assigns `expense.payments = ...`, which lazy-loads on a real
            # async session (tests/test_transaction_integrity_pg.py fails the same way on an
            # untouched checkout). The expense is committed and the notifications are stored
            # before that line, which is all this test checks.
            pass
    assert await rows_for(real_store, alex.id) == []
    assert len(await rows_for(real_store, blair.id)) == 1
    assert len(await rows_for(real_store, casey.id)) == 1


async def test_endpoints_list_newest_first_with_pagination_and_unread_state(real_store, api):
    alex, blair, _ = real_store["world"]["users"]
    for i in range(5):
        await notifications.notify_users([blair.id], alex.id, "member_left", f"r-{i}")

    first = (await api.get("/api/v1/notifications?limit=2", headers=bearer(blair))).json()
    assert len(first["items"]) == 2 and first["unread_count"] == 5 and first["next_cursor"]
    second = (
        await api.get(f"/api/v1/notifications?limit=10&cursor={first['next_cursor']}", headers=bearer(blair))
    ).json()
    assert len(second["items"]) == 3 and second["next_cursor"] is None
    stamps = [i["created_at"] for i in first["items"] + second["items"]]
    assert stamps == sorted(stamps, reverse=True)
    assert all(i["is_read"] is False for i in first["items"])

    count_resp = await api.get("/api/v1/notifications/unread-count", headers=bearer(blair))
    assert count_resp.json() == {"unread_count": 5}


async def test_mark_read_and_read_all_and_per_user_isolation(real_store, api):
    alex, blair, casey = real_store["world"]["users"]
    await notifications.notify_users([blair.id, casey.id], alex.id, "member_left", "r-1")
    await notifications.notify_users([blair.id, casey.id], alex.id, "member_left", "r-2")
    blair_items = (await api.get("/api/v1/notifications", headers=bearer(blair))).json()["items"]
    casey_items = (await api.get("/api/v1/notifications", headers=bearer(casey))).json()["items"]
    assert len(blair_items) == 2 and len(casey_items) == 2
    assert {i["id"] for i in blair_items}.isdisjoint({i["id"] for i in casey_items})

    # Casey cannot read Blair's notification: 404, and it stays unread.
    stolen = await api.patch(f"/api/v1/notifications/{blair_items[0]['id']}/read", headers=bearer(casey))
    assert stolen.status_code == 404
    assert (await api.get("/api/v1/notifications/unread-count", headers=bearer(blair))).json()["unread_count"] == 2

    own = await api.patch(f"/api/v1/notifications/{blair_items[0]['id']}/read", headers=bearer(blair))
    assert own.status_code == 200 and own.json()["is_read"] is True
    first_read_at = own.json()["read_at"]
    again = await api.patch(f"/api/v1/notifications/{blair_items[0]['id']}/read", headers=bearer(blair))
    assert again.json()["read_at"] == first_read_at  # idempotent

    done = await api.patch("/api/v1/notifications/read-all", headers=bearer(blair))
    assert done.json() == {"updated": 1}
    assert (await api.get("/api/v1/notifications/unread-count", headers=bearer(blair))).json()["unread_count"] == 0
    assert (await api.get("/api/v1/notifications/unread-count", headers=bearer(casey))).json()["unread_count"] == 2


async def test_unauthenticated_and_unknown_ids_are_rejected(real_store, api):
    assert (await api.get("/api/v1/notifications")).status_code in (401, 403)
    assert (await api.get("/api/v1/notification-preferences")).status_code in (401, 403)
    _, blair, _ = real_store["world"]["users"]
    missing = await api.patch(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=bearer(blair))
    assert missing.status_code == 404
    bad_cursor = await api.get("/api/v1/notifications?cursor=garbage", headers=bearer(blair))
    assert bad_cursor.status_code == 400


async def test_preferences_default_enabled_update_and_stay_per_user(real_store, api):
    alex, blair, _ = real_store["world"]["users"]
    initial = (await api.get("/api/v1/notification-preferences", headers=bearer(blair))).json()
    assert len(initial["preferences"]) == 13  # 11 + T-44's two recurring-expense kinds
    assert all(p["enabled"] for p in initial["preferences"])
    # T-50: password_changed is a security notice and is the only one that cannot be switched off.
    assert {p["kind"] for p in initial["preferences"] if not p["can_disable"]} == {"password_changed"}

    resp = await api.put(
        "/api/v1/notification-preferences",
        json={"preferences": [{"kind": "member_joined", "enabled": False}]},
        headers=bearer(blair),
    )
    assert resp.status_code == 200
    by_kind = {p["kind"]: p["enabled"] for p in resp.json()["preferences"]}
    assert by_kind["member_joined"] is False and by_kind["member_left"] is True

    other = (await api.get("/api/v1/notification-preferences", headers=bearer(alex))).json()
    assert all(p["enabled"] for p in other["preferences"])

    bad = await api.put(
        "/api/v1/notification-preferences",
        json={"preferences": [{"kind": "nope", "enabled": False}]},
        headers=bearer(blair),
    )
    assert bad.status_code == 422
    # A client cannot pass someone else's user id.
    extra = await api.put(
        "/api/v1/notification-preferences",
        json={"preferences": [{"kind": "member_left", "enabled": False}], "user_id": str(alex.id)},
        headers=bearer(blair),
    )
    assert extra.status_code == 422

    sent = await notifications.notify_users([blair.id], alex.id, "member_joined", "r-9")
    assert sent == []


# ==============================================================================
# Recipients come from committed membership (T-36 review fix), on real PostgreSQL
# ==============================================================================

from datetime import UTC, datetime  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.models.group import GroupMember  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.group import CreateInvitationRequest  # noqa: E402
from app.services import group_service  # noqa: E402


async def add_user(real_store: dict[str, Any], name: str) -> User:
    user = User(
        id=uuid.uuid4(), email=f"{name}@example.com", name=name.title(),
        hashed_password="x", is_active=True,
    )
    async with real_store["sessions"]() as s:
        s.add(user)
        await s.commit()
    return user


async def kinds_for(real_store: dict[str, Any], user: User) -> list[str]:
    return sorted(r.kind for r in await rows_for(real_store, user.id))


async def test_snapshot_would_notify_a_member_removed_after_it_was_loaded(real_store):
    """A removed member must not get a post-commit expense notice, even if the group
    object loaded at the start of the request still lists them as active."""
    alex, blair, casey = real_store["world"]["users"]
    group_id = real_store["world"]["group"].id
    async with real_store["sessions"]() as request_session:
        group = await group_service.get_group_or_404(request_session, group_id)  # request start
        assert {m.user_id for m in group.members if m.status == "active"} == {alex.id, blair.id, casey.id}

        async with real_store["sessions"]() as other:  # concurrent removal commits meanwhile
            await other.execute(
                text("UPDATE group_members SET status='removed' WHERE group_id=:g AND user_id=:u"),
                {"g": group_id, "u": blair.id},
            )
            await other.commit()

        # The loaded collection is a stale snapshot (the review's concern, confirmed).
        assert blair.id in {m.user_id for m in group.members if m.status == "active"}

        await notifications.notify_group_members(
            group, alex.id, "group_expense_created", "e-1", {"description": "x"}, db=request_session
        )
    assert await kinds_for(real_store, blair) == []  # removed member: nothing
    assert await kinds_for(real_store, casey) == ["group_expense_created"]
    assert await kinds_for(real_store, alex) == []  # actor


async def test_loaded_members_are_not_refreshed_by_get_group_or_404(real_store):
    """Documents why recipients are read with a column query: calling get_group_or_404 again
    on the same session does NOT refresh an already-loaded members collection."""
    alex, _, _ = real_store["world"]["users"]
    group_id = real_store["world"]["group"].id
    dana = await add_user(real_store, "dana")
    async with real_store["sessions"]() as s:
        group = await group_service.get_group_or_404(s, group_id)
        s.add(GroupMember(group_id=group_id, user_id=dana.id, role="member", status="active",
                          joined_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
        await s.commit()
        again = await group_service.get_group_or_404(s, group_id)
        assert again is group
        assert dana.id not in {m.user_id for m in again.members}  # stale collection
        fresh = await notifications.active_member_roles(s, group_id)
        assert dana.id in fresh  # the column query sees the committed row


async def test_join_by_code_notifies_other_active_members_not_the_joiner(real_store):
    alex, blair, casey = real_store["world"]["users"]
    group_id = real_store["world"]["group"].id
    dana = await add_user(real_store, "dana")
    async with real_store["sessions"]() as s:
        code = (await group_service.generate_join_code(s, group_id, alex)).code
    async with real_store["sessions"]() as s:
        joined = await group_service.join_group_by_code(s, dana, code)
    assert joined.name == "Flat Expenses"
    for member in (alex, blair, casey):
        assert await kinds_for(real_store, member) == ["member_joined"]
    assert await kinds_for(real_store, dana) == []


async def test_invitation_accept_and_decline_recipients(real_store):
    alex, blair, casey = real_store["world"]["users"]
    group_id = real_store["world"]["group"].id
    dana = await add_user(real_store, "dana")
    erin = await add_user(real_store, "erin")

    async with real_store["sessions"]() as s:
        inv_d = await group_service.create_invitation(s, group_id, CreateInvitationRequest(user_id=dana.id), alex)
    async with real_store["sessions"]() as s:
        inv_e = await group_service.create_invitation(s, group_id, CreateInvitationRequest(user_id=erin.id), alex)
    assert await kinds_for(real_store, dana) == ["invitation_received"]
    assert await kinds_for(real_store, alex) == []

    async with real_store["sessions"]() as s:
        await group_service.accept_invitation(s, inv_d.id, dana)
    async with real_store["sessions"]() as s:
        await group_service.decline_invitation(s, inv_e.id, erin)

    # The inviter hears accepted and declined (and no "joined"); other members hear "joined";
    # the joiner and the decliner hear nothing beyond their own invitation.
    assert await kinds_for(real_store, alex) == ["invitation_accepted", "invitation_declined"]
    assert await kinds_for(real_store, blair) == ["member_joined"]
    assert await kinds_for(real_store, casey) == ["member_joined"]
    assert await kinds_for(real_store, dana) == ["invitation_received"]
    assert await kinds_for(real_store, erin) == ["invitation_received"]


async def test_removal_and_leaving_recipients_use_committed_admins(real_store):
    alex, blair, casey = real_store["world"]["users"]
    group_id = real_store["world"]["group"].id
    async with real_store["sessions"]() as s:  # make casey a second admin
        await s.execute(
            text("UPDATE group_members SET role='admin' WHERE group_id=:g AND user_id=:u"),
            {"g": group_id, "u": casey.id},
        )
        await s.commit()

    async with real_store["sessions"]() as s:  # alex removes blair
        await group_service.remove_member(s, group_id, blair.id, alex)
    assert await kinds_for(real_store, blair) == ["member_removed"]  # told once: you were removed
    assert await kinds_for(real_store, casey) == ["member_removed"]  # the other admin
    assert await kinds_for(real_store, alex) == []  # the actor

    async with real_store["sessions"]() as s:  # casey leaves
        await group_service.remove_member(s, group_id, casey.id, casey)
    assert await kinds_for(real_store, alex) == ["member_left"]  # the remaining admin
    assert await kinds_for(real_store, casey) == ["member_removed"]  # nothing about her own leaving
    assert await kinds_for(real_store, blair) == ["member_removed"]  # removed members get nothing more


async def test_migration_011_locks_down_both_tables_for_api_roles(real_store):
    """Run the real migration's upgrade() and check RLS and API-role privileges.

    Supabase grants new public tables to anon/authenticated through default privileges;
    this simulates that on the throwaway database. The connecting role is a superuser, so
    the owner-keeps-access half is verified separately with a non-superuser owner (see the
    T-36 review-fix report); this test checks the denial half.
    """
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "011_create_notifications.py"
    spec = importlib.util.spec_from_file_location("m011_lock", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    async with real_store["admin"].connect() as admin:
        for role in ("anon", "authenticated"):
            exists = (await admin.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": role}
            )).scalar_one()
            if not exists:
                await admin.execute(text(f"CREATE ROLE {role} NOLOGIN"))

    def run_upgrade(sync_conn: Any) -> None:
        sync_conn.execute(text("DROP TABLE IF EXISTS notification_preferences, notifications"))
        sync_conn.execute(text("GRANT USAGE ON SCHEMA public TO anon, authenticated"))
        sync_conn.execute(text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon, authenticated"
        ))
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.upgrade()

    async with real_store["engine"].begin() as conn:
        await conn.run_sync(run_upgrade)
        for table in ("notifications", "notification_preferences"):
            rls = (await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname=:t"), {"t": table}
            )).scalar_one()
            policies = (await conn.execute(
                text("SELECT count(*) FROM pg_policies WHERE tablename=:t"), {"t": table}
            )).scalar_one()
            assert rls is True and policies == 0
            for role in ("anon", "authenticated", "public"):
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    granted = (await conn.execute(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": role, "t": table, "p": priv},
                    )).scalar_one()
                    assert granted is False, f"{role} still has {priv} on {table}"
