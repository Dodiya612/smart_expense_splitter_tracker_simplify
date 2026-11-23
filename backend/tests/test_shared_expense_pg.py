"""Real-PostgreSQL regression tests for shared expense creation (T-36 final fix).

`create_shared_expense` used to end with `expense.payments = payment_records`, which makes
SQLAlchemy read the never-loaded old collection: implicit async I/O that raises
MissingGreenlet on a real session. The in-memory fake sessions cannot reproduce that, so
these tests run the real service, the real notification store and the real endpoints on
a throwaway local PostgreSQL.

They are SKIPPED when no local PostgreSQL is reachable, and they never touch Supabase
(same localhost-only rule and COINSCIOUS_TEST_PG_URL setting as
tests/test_transaction_integrity_pg.py).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.expense import AuditEvent, Expense, ExpensePayment, ExpenseShare
from app.models.idempotency import IdempotencyRecord
from app.models.notification import Notification
from app.schemas.shared_expense import SharedExpenseCreateRequest
from app.services import shared_expense_service
from tests.test_notifications_pg import api, bearer, rows_for, real_store  # noqa: F401 - fixtures
from tests.test_transaction_integrity_pg import (  # noqa: F401 - pg is a fixture
    count,
    kill_connection_before_commit,
    pg,
)


def body(category_id: uuid.UUID, amount: int = 300000, **extra: Any) -> SharedExpenseCreateRequest:
    return SharedExpenseCreateRequest(
        amount_paise=amount, description="Groceries", category_id=category_id, **extra
    )


async def create(real_store: dict[str, Any], user: Any, request: SharedExpenseCreateRequest, key: str | None = None):
    async with real_store["sessions"]() as s:
        return await shared_expense_service.create_shared_expense(
            s, real_store["world"]["group"].id, user, request, idempotency_key=key
        )


async def total(real_store: dict[str, Any], model: Any) -> int:
    return await count(real_store["sessions"], select(func.count()).select_from(model))


# ------------------------------------------------------------------------------
# 1-3. Creation works on a real async session and persists / returns the right data
# ------------------------------------------------------------------------------


async def test_create_succeeds_without_missing_greenlet_and_persists_everything(real_store):
    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]

    created, replay = await create(real_store, alex, body(category.id))

    assert replay is False
    assert await total(real_store, Expense) == 1
    assert await total(real_store, ExpensePayment) == 1
    assert await total(real_store, ExpenseShare) == 3
    assert await total(real_store, AuditEvent) == 1
    async with real_store["sessions"]() as s:
        expense = (await s.execute(select(Expense))).scalar_one()
        payments = (await s.execute(select(ExpensePayment))).scalars().all()
        shares = (await s.execute(select(ExpenseShare))).scalars().all()
    assert expense.id == created.id and expense.amount_minor == 300000 and expense.user_id == alex.id
    assert [(p.user_id, p.amount_paise) for p in payments] == [(alex.id, 300000)]
    assert sorted(sh.amount_paise for sh in shares) == [100000] * 3
    assert {sh.user_id for sh in shares} == {alex.id, blair.id, casey.id}


async def test_response_carries_the_payments_and_shares_that_were_written(real_store):
    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]

    created, _ = await create(real_store, alex, body(category.id))

    assert created.amount_paise == 300000 and created.description == "Groceries"
    assert created.split_mode == "equal" and created.version == 1
    assert [(p.user_id, p.amount_paise) for p in created.payments] == [(alex.id, 300000)]
    assert sorted((sh.user_id, sh.amount_paise) for sh in created.shares) == sorted(
        (u.id, 100000) for u in (alex, blair, casey)
    )
    # The create response matches what the read path returns for the stored expense.
    async with real_store["sessions"]() as s:
        fetched = await shared_expense_service.get_shared_expense(
            s, real_store["world"]["group"].id, created.id, alex
        )
    assert fetched.model_dump(include={"id", "amount_paise", "payments", "shares", "split_mode"}) == (
        created.model_dump(include={"id", "amount_paise", "payments", "shares", "split_mode"})
    )


async def test_multi_payer_expense_returns_every_payment(real_store):
    alex, blair, _ = real_store["world"]["users"]
    category = real_store["world"]["category"]
    created, _ = await create(
        real_store, alex, body(category.id, payments={str(alex.id): 200000, str(blair.id): 100000})
    )
    assert sorted((p.user_id, p.amount_paise) for p in created.payments) == sorted(
        [(alex.id, 200000), (blair.id, 100000)]
    )
    assert await total(real_store, ExpensePayment) == 2


async def test_endpoint_returns_201_with_the_unchanged_response_shape(real_store, api):
    alex, _, _ = real_store["world"]["users"]
    category = real_store["world"]["category"]
    resp = await api.post(
        f"/api/v1/groups/{real_store['world']['group'].id}/expenses",
        json={"amount_paise": 300000, "description": "Groceries", "category_id": str(category.id)},
        headers=bearer(alex),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert {"id", "groupId", "amountPaise", "description", "splitMode", "payments", "shares", "version"} <= set(data)
    assert data["amountPaise"] == 300000 and data["version"] == 1
    assert data["payments"] == [{"userId": str(alex.id), "amountPaise": 300000}]
    assert sorted(s["amountPaise"] for s in data["shares"]) == [100000] * 3


# ------------------------------------------------------------------------------
# 4 + 8. Idempotency: replays return the original and never duplicate rows or notices
# ------------------------------------------------------------------------------


async def test_idempotency_key_replays_the_original_and_creates_one_expense(real_store):
    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]

    first, first_replay = await create(real_store, alex, body(category.id), key="k-1")
    second, second_replay = await create(real_store, alex, body(category.id), key="k-1")
    third, third_replay = await create(real_store, alex, body(category.id), key="k-1")

    assert (first_replay, second_replay, third_replay) == (False, True, True)
    assert first.id == second.id == third.id
    assert second.payments == first.payments and second.shares == first.shares
    assert await total(real_store, Expense) == 1
    assert await total(real_store, ExpenseShare) == 3
    assert await total(real_store, IdempotencyRecord) == 1
    # Retrying never creates a second notification for anyone.
    assert [len(await rows_for(real_store, u.id)) for u in (alex, blair, casey)] == [0, 1, 1]
    assert await total(real_store, Notification) == 2


async def test_same_key_with_a_different_body_is_a_conflict_and_notifies_nobody_more(real_store):
    alex, blair, _ = real_store["world"]["users"]
    category = real_store["world"]["category"]
    await create(real_store, alex, body(category.id), key="k-2")
    with pytest.raises(HTTPException) as exc:
        await create(real_store, alex, body(category.id, amount=450000), key="k-2")
    assert exc.value.status_code == 409
    assert await total(real_store, Expense) == 1
    assert len(await rows_for(real_store, blair.id)) == 1


async def test_endpoint_replay_header_and_single_notification_set(real_store, api):
    alex, blair, _ = real_store["world"]["users"]
    category = real_store["world"]["category"]
    url = f"/api/v1/groups/{real_store['world']['group'].id}/expenses"
    payload = {"amount_paise": 300000, "description": "Groceries", "category_id": str(category.id)}
    headers = {**bearer(alex), "Idempotency-Key": "http-1"}
    first = await api.post(url, json=payload, headers=headers)
    again = await api.post(url, json=payload, headers=headers)
    assert first.status_code == 201 and again.status_code == 201
    assert "x-idempotent-replay" not in first.headers
    assert again.headers.get("x-idempotent-replay") == "true"
    assert again.json() == first.json()
    assert await total(real_store, Expense) == 1
    assert len(await rows_for(real_store, blair.id)) == 1


# ------------------------------------------------------------------------------
# 5 + 6. Notifications are stored after commit, for the right people, with the right data
# ------------------------------------------------------------------------------


async def test_created_notification_is_persisted_after_commit_for_other_members_only(real_store):
    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]

    created, _ = await create(real_store, alex, body(category.id))

    assert await rows_for(real_store, alex.id) == []  # the actor is never notified
    for member in (blair, casey):
        (row,) = await rows_for(real_store, member.id)
        assert row.kind == "group_expense_created"
        assert row.group_id == real_store["world"]["group"].id
        assert row.dedupe_key == f"group_expense_created:{created.id}:{member.id}"
        assert row.payload["expense_id"] == str(created.id)
        assert row.payload["amount_paise"] == 300000
        assert row.payload["description"] == "Groceries"
        assert row.title == "New expense in Flat Expenses"
        assert row.body == "Alex added Groceries (₹3,000)."
        assert row.read_at is None


async def test_a_member_who_left_before_the_notice_is_not_notified(real_store):
    from sqlalchemy import text

    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]
    async with real_store["sessions"]() as s:
        await s.execute(
            text("UPDATE group_members SET status='left' WHERE user_id=:u"), {"u": blair.id}
        )
        await s.commit()
    await create(real_store, alex, body(category.id, participant_user_ids=[alex.id, casey.id]))
    assert await rows_for(real_store, blair.id) == []
    assert len(await rows_for(real_store, casey.id)) == 1


# ------------------------------------------------------------------------------
# 7. A failed or rolled-back transaction produces no notification
# ------------------------------------------------------------------------------


async def test_connection_killed_before_commit_writes_nothing_and_notifies_nobody(real_store):
    alex = real_store["world"]["users"][0]
    seen: dict[str, Any] = {}
    async with real_store["sessions"]() as s:
        kill_connection_before_commit(s, real_store["admin"], seen)
        with pytest.raises(SQLAlchemyError):
            await shared_expense_service.create_shared_expense(
                s, real_store["world"]["group"].id, alex, body(real_store["world"]["category"].id)
            )
    assert seen.get("killed") is True
    assert await total(real_store, Expense) == 0
    assert await total(real_store, ExpenseShare) == 0
    assert await total(real_store, Notification) == 0


async def test_rejected_request_writes_nothing_and_notifies_nobody(real_store):
    alex = real_store["world"]["users"][0]
    with pytest.raises(HTTPException) as exc:
        await create(real_store, alex, body(uuid.uuid4()))  # unknown category
    assert exc.value.status_code == 400
    assert await total(real_store, Expense) == 0
    assert await total(real_store, Notification) == 0


async def test_retry_after_a_killed_attempt_creates_one_expense_and_one_notice_per_member(real_store):
    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]
    seen: dict[str, Any] = {}
    async with real_store["sessions"]() as s:
        kill_connection_before_commit(s, real_store["admin"], seen)
        with pytest.raises(SQLAlchemyError):
            await shared_expense_service.create_shared_expense(
                s, real_store["world"]["group"].id, alex, body(category.id), idempotency_key="k-kill"
            )
    assert await total(real_store, Notification) == 0

    created, replay = await create(real_store, alex, body(category.id), key="k-kill")
    again, again_replay = await create(real_store, alex, body(category.id), key="k-kill")

    assert (replay, again_replay) == (False, True) and created.id == again.id
    assert await total(real_store, Expense) == 1
    assert [len(await rows_for(real_store, u.id)) for u in (alex, blair, casey)] == [0, 1, 1]


# ------------------------------------------------------------------------------
# Related paths: update and delete use the same real session after commit
# ------------------------------------------------------------------------------


async def test_update_and_delete_work_on_a_real_session_and_notify_with_versioned_keys(real_store, api):
    alex, blair, casey = real_store["world"]["users"]
    category = real_store["world"]["category"]
    group_id = real_store["world"]["group"].id
    created, _ = await create(real_store, alex, body(category.id))
    url = f"/api/v1/groups/{group_id}/expenses/{created.id}"

    for version, description in ((1, "First edit"), (2, "Second edit")):
        resp = await api.patch(
            url, json={"description": description, "version": version}, headers=bearer(alex)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["version"] == version + 1
        assert resp.json()["description"] == description

    resp = await api.delete(f"{url}?version=3", headers=bearer(alex))
    assert resp.status_code == 200, resp.text

    kinds = sorted(r.kind for r in await rows_for(real_store, blair.id))
    assert kinds == [
        "group_expense_created", "group_expense_deleted",
        "group_expense_updated", "group_expense_updated",
    ]
    assert await rows_for(real_store, alex.id) == []
    assert len(await rows_for(real_store, casey.id)) == 4
