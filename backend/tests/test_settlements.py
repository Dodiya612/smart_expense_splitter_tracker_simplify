"""API tests for balances and settlements (US-20 / T-32).

Reuses the in-memory fake database from tests/test_shared_expenses.py and adds
the settlements and idempotency_records tables to it.
"""

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import create_access_token
from app.models.expense import ExpensePayment, ExpenseShare
from app.models.group import GroupMemberStatus
from app.models.idempotency import IdempotencyRecord
from app.models.settlement import Settlement
from app.schemas.ledger import ExpenseRecord, SettlementRecord
from app.services.ledger import net_positions, simplify
from tests import test_shared_expenses as shared
from tests.test_shared_expenses import FakeExpenseDB, FakeResult, FakeSharedExpenseAsyncSession

# Re-use the shared-expense fixtures (fake DB, users, group, auth headers, client).
# `fake_session` is overridden below to add settlements and idempotency records.
user_a = shared.user_a
user_b = shared.user_b
user_c = shared.user_c
user_stranger = shared.user_stranger
sample_category = shared.sample_category
sample_group = shared.sample_group
auth_headers_user_a = shared.auth_headers_user_a
auth_headers_user_b = shared.auth_headers_user_b
auth_headers_stranger = shared.auth_headers_stranger
client = shared.client


# ==============================================================================
# Fake session with settlements and idempotency records
# ==============================================================================


class FakeSettlementDB(FakeExpenseDB):
    def __init__(self):
        super().__init__()
        self.settlements: dict[uuid.UUID, Settlement] = {}
        self.idempotency_records: dict[tuple[uuid.UUID, str], IdempotencyRecord] = {}


class FakeSettlementAsyncSession(FakeSharedExpenseAsyncSession):
    def __init__(self, db: FakeSettlementDB):
        super().__init__(db)
        self.db: FakeSettlementDB = db
        self._flushed_rows: list[tuple[dict, tuple[uuid.UUID, uuid.UUID]]] = []

    async def flush(self):
        # Like a real session: rows flushed inside a transaction are visible to later
        # queries in it (T-34 edit recomputes balances after flushing new shares).
        await super().flush()
        for obj in self.pending:
            if isinstance(obj, ExpensePayment):
                key = (obj.expense_id, obj.user_id)
                self.db.expense_payments[key] = obj
                self._flushed_rows.append((self.db.expense_payments, key))
            elif isinstance(obj, ExpenseShare):
                key = (obj.expense_id, obj.user_id)
                self.db.expense_shares[key] = obj
                self._flushed_rows.append((self.db.expense_shares, key))

    async def commit(self):
        if self.fail_on_commit:
            raise RuntimeError("Simulated database failure during flush/commit")
        for obj in self.pending:
            if isinstance(obj, Settlement):
                self.db.settlements[obj.id] = obj
            elif isinstance(obj, IdempotencyRecord):
                self.db.idempotency_records[(obj.user_id, obj.key)] = obj
        self._flushed_rows.clear()
        await super().commit()

    async def rollback(self):
        for table, key in self._flushed_rows:
            table.pop(key, None)
        self._flushed_rows.clear()
        await super().rollback()

    async def execute(self, stmt):
        sql_str = str(stmt).lower()
        params = stmt.compile().params

        if "from settlements" in sql_str:
            gid = next(
                (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            sid = next(
                (v for k, v in params.items() if (k.startswith("id_") or k == "id") and isinstance(v, uuid.UUID)),
                None,
            )
            status_val = next(
                (v for k, v in params.items() if k.startswith("status") and isinstance(v, str)),
                None,
            )
            matched = list(self.db.settlements.values())
            if gid is not None:
                matched = [s for s in matched if s.group_id == gid]
            if sid is not None:
                matched = [s for s in matched if s.id == sid]
            if status_val is not None:
                matched = [s for s in matched if s.status == status_val]
            if "desc" in sql_str:
                matched.sort(key=lambda s: (s.settlement_date, s.created_at), reverse=True)
            else:
                matched.sort(key=lambda s: s.created_at)
            return FakeResult(matched)

        if "from audit_events" in sql_str and "join settlements" in sql_str:
            # Group history (shared_expense_service.get_group_history): audit events of
            # the group's expenses, of the group itself and of the group's settlements.
            gid = next(
                (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            entity_ids = {e.id for e in self.db.expenses.values() if e.group_id == gid}
            entity_ids |= {s.id for s in self.db.settlements.values() if s.group_id == gid}
            if gid is not None:
                entity_ids.add(gid)
            matched = [a for a in self.db.audit_events.values() if a.entity_id in entity_ids]
            matched.sort(key=lambda a: a.created_at, reverse=True)
            return FakeResult(matched)

        if "from idempotency_records" in sql_str:
            uid = next(
                (v for k, v in params.items() if "user_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            key = next(
                (v for k, v in params.items() if k.startswith("key") and isinstance(v, str)),
                None,
            )
            rec = self.db.idempotency_records.get((uid, key))
            return FakeResult([rec] if rec else [])

        return await super().execute(stmt)


@pytest.fixture
def expense_db():
    return FakeSettlementDB()


@pytest.fixture
def fake_session(expense_db):
    return FakeSettlementAsyncSession(expense_db)


@pytest.fixture
def auth_headers_user_c(user_c):
    token = create_access_token(user_c.id, email=user_c.email)
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# Helpers
# ==============================================================================


async def add_expense(client, group, category, headers, amount_paise, participants=None):
    body = {
        "amount_paise": amount_paise,
        "description": "Shared bill",
        "category_id": str(category.id),
        "split_mode": "equal",
    }
    if participants is not None:
        body["participant_user_ids"] = [str(p.id) for p in participants]
    resp = await client.post(f"/api/v1/groups/{group.id}/expenses", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def settle(client, group, headers, payer, payee, amount_paise=None, full=False, key=None, **extra):
    body = {"payer_id": str(payer.id), "payee_id": str(payee.id), "is_full_settlement": full}
    if amount_paise is not None:
        body["amount_paise"] = amount_paise
    body.update(extra)
    hdrs = dict(headers)
    if key is not None:
        hdrs["Idempotency-Key"] = key
    return await client.post(f"/api/v1/groups/{group.id}/settlements", json=body, headers=hdrs)


async def get_balances(client, group, headers):
    resp = await client.get(f"/api/v1/groups/{group.id}/balances", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def ledger_from_fake_db(db, group_id):
    """Recompute net positions straight from stored rows with the pure ledger engine."""
    expenses = []
    for exp in db.expenses.values():
        if exp.group_id != group_id or exp.deleted_at is not None:
            continue
        expenses.append(
            ExpenseRecord(
                expense_id=str(exp.id),
                amount_paise=exp.amount_minor,
                payments={
                    str(p.user_id): p.amount_paise
                    for p in db.expense_payments.values()
                    if p.expense_id == exp.id
                },
                shares={
                    str(s.user_id): s.amount_paise
                    for s in db.expense_shares.values()
                    if s.expense_id == exp.id
                },
            )
        )
    settlements = [
        SettlementRecord(from_user=str(s.payer_id), to_user=str(s.payee_id), amount_paise=s.amount_paise)
        for s in db.settlements.values()
        if s.group_id == group_id and s.status == "completed"
    ]
    return net_positions(expenses, settlements)


# ==============================================================================
# Demo example (docs/PRODUCT.md section 05, ledger.md section 8)
# ==============================================================================


@pytest.mark.asyncio
async def test_demo_alex_pays_3000_blair_repays_1000(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    """Alex (A) pays ₹3,000 split three ways; Blair (B) repays ₹1,000.

    Expected: Alex +₹1,000.00, Blair ₹0, Casey (C) −₹1,000.00.
    """
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    before = await get_balances(client, sample_group, auth_headers_user_a)
    assert before["net_positions"] == {
        str(user_a.id): 200000,
        str(user_b.id): -100000,
        str(user_c.id): -100000,
    }

    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=100000)
    assert resp.status_code == 201, resp.text
    stl = resp.json()
    assert stl["amount_paise"] == 100000
    assert stl["payer_id"] == str(user_b.id)
    assert stl["payee_id"] == str(user_a.id)
    assert stl["is_partial"] is False
    assert stl["remaining_debt_paise"] == 0
    assert stl["status"] == "completed"

    after = await get_balances(client, sample_group, auth_headers_user_a)
    assert after["net_positions"] == {
        str(user_a.id): 100000,
        str(user_b.id): 0,
        str(user_c.id): -100000,
    }
    members = {m["user_id"]: m for m in after["members"]}
    assert members[str(user_a.id)]["status"] == "creditor"
    assert members[str(user_a.id)]["receives_paise"] == 100000
    assert members[str(user_b.id)]["status"] == "settled"
    assert members[str(user_c.id)]["status"] == "debtor"
    assert members[str(user_c.id)]["owes_paise"] == 100000
    assert after["total_debt_paise"] == 100000
    assert after["currency"] == "INR"
    assert after["suggested_transfers"] == [
        {"from_user": str(user_c.id), "to_user": str(user_a.id), "amount_paise": 100000}
    ]

    simplified = await client.get(
        f"/api/v1/groups/{sample_group.id}/balances/simplified", headers=auth_headers_user_a
    )
    assert simplified.status_code == 200
    assert simplified.json() == {
        "group_id": str(sample_group.id),
        "suggested_transfers": [
            {"from_user": str(user_c.id), "to_user": str(user_a.id), "amount_paise": 100000}
        ],
        "total_transfers": 1,
        "total_amount_paise": 100000,
    }

    # A settlement never counts as spending or income: no expense rows were added
    # and every member's share of the bill is unchanged.
    assert len(expense_db.expenses) == 1
    assert sorted(s.amount_paise for s in expense_db.expense_shares.values()) == [100000] * 3


# ==============================================================================
# Full and partial settlements
# ==============================================================================


@pytest.mark.asyncio
async def test_full_settlement_settles_everything_owed(
    client, sample_group, sample_category, user_a, user_c,
    auth_headers_user_a, auth_headers_user_c,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_c, user_c, user_a, full=True)
    assert resp.status_code == 201, resp.text
    stl = resp.json()
    assert stl["amount_paise"] == 100000
    assert stl["is_partial"] is False
    assert stl["remaining_debt_paise"] == 0

    bal = await get_balances(client, sample_group, auth_headers_user_a)
    assert bal["net_positions"][str(user_c.id)] == 0
    assert bal["net_positions"][str(user_a.id)] == 100000


@pytest.mark.asyncio
async def test_full_settlement_with_matching_amount_is_accepted_and_mismatch_rejected(
    client, sample_group, sample_category, user_a, user_c,
    auth_headers_user_a, auth_headers_user_c, expense_db,
):
    """Mobile sends amount_paise together with is_full_settlement; they must agree."""
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    bad = await settle(client, sample_group, auth_headers_user_c, user_c, user_a, amount_paise=99999, full=True)
    assert bad.status_code == 400
    assert bad.json()["code"] == "AMOUNT_MISMATCH"
    assert len(expense_db.settlements) == 0

    ok = await settle(client, sample_group, auth_headers_user_c, user_c, user_a, amount_paise=100000, full=True)
    assert ok.status_code == 201
    assert ok.json()["amount_paise"] == 100000


@pytest.mark.asyncio
async def test_partial_settlement_reduces_debt_and_lowers_ceiling(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=40000)
    assert resp.status_code == 201, resp.text
    stl = resp.json()
    assert stl["is_partial"] is True
    assert stl["remaining_debt_paise"] == 60000

    bal = await get_balances(client, sample_group, auth_headers_user_a)
    assert bal["net_positions"][str(user_b.id)] == -60000
    assert bal["net_positions"][str(user_a.id)] == 160000

    # The ceiling is now what is still owed (60,000 paise).
    over = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=60001)
    assert over.status_code == 400
    assert over.json()["code"] == "AMOUNT_EXCEEDS_OUTSTANDING"

    rest = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=60000)
    assert rest.status_code == 201
    assert rest.json()["is_partial"] is False
    assert len(expense_db.settlements) == 2


# ==============================================================================
# Rejections
# ==============================================================================


@pytest.mark.asyncio
async def test_over_payment_rejected(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=100001)
    assert resp.status_code == 400
    assert resp.json()["code"] == "AMOUNT_EXCEEDS_OUTSTANDING"
    assert len(expense_db.settlements) == 0
    assert len([a for a in expense_db.audit_events.values() if a.entity_type == "settlement"]) == 0


@pytest.mark.asyncio
async def test_settlement_rejected_when_payer_owes_nothing_or_payee_is_not_owed(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    # A is a creditor, so A cannot "repay" B.
    resp = await settle(client, sample_group, auth_headers_user_a, user_a, user_b, amount_paise=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "PAYER_NOT_DEBTOR"

    # C is a debtor, so B cannot repay C.
    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_c, amount_paise=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "PAYEE_NOT_CREDITOR"


@pytest.mark.asyncio
async def test_payer_equal_to_payee_rejected(
    client, sample_group, sample_category, user_b, auth_headers_user_a, auth_headers_user_b, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_b, amount_paise=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "SELF_SETTLEMENT_PROHIBITED"
    assert len(expense_db.settlements) == 0


@pytest.mark.asyncio
async def test_non_member_payer_or_payee_rejected(
    client, sample_group, sample_category, user_a, user_b, user_c, user_stranger,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_stranger, amount_paise=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "PAYEE_NOT_IN_GROUP"

    resp = await settle(client, sample_group, auth_headers_user_a, user_stranger, user_a, amount_paise=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "PAYER_NOT_IN_GROUP"

    # A member who has left the group is no longer an active member.
    expense_db.group_members[(sample_group.id, user_c.id)].status = GroupMemberStatus.LEFT.value
    resp = await settle(client, sample_group, auth_headers_user_a, user_c, user_a, amount_paise=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "PAYER_NOT_IN_GROUP"

    assert len(expense_db.settlements) == 0


@pytest.mark.asyncio
async def test_member_cannot_record_settlement_between_two_other_members(
    client, sample_group, sample_category, user_a, user_c,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    """B is a plain member; only the payer, the payee or an admin may record C -> A."""
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_b, user_c, user_a, amount_paise=100)
    assert resp.status_code == 403
    assert resp.json()["code"] == "SETTLEMENT_NOT_ALLOWED"

    # A is the admin (and the payee) and may record it.
    resp = await settle(client, sample_group, auth_headers_user_a, user_c, user_a, amount_paise=100)
    assert resp.status_code == 201
    assert len(expense_db.settlements) == 1


@pytest.mark.asyncio
async def test_invalid_amounts_rejected(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a, auth_headers_user_b,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    for bad in (0, -100, 10.5, True):
        resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=bad)
        assert resp.status_code == 422, bad

    missing = await settle(client, sample_group, auth_headers_user_b, user_b, user_a)
    assert missing.status_code == 400
    assert missing.json()["code"] == "AMOUNT_REQUIRED"

    # Protected / unknown fields are rejected, not silently trusted.
    tampered = await settle(
        client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=100, created_by=str(user_a.id)
    )
    assert tampered.status_code == 422


# ==============================================================================
# Authorization: strangers get 404
# ==============================================================================


@pytest.mark.asyncio
async def test_stranger_gets_404_on_all_balance_and_settlement_endpoints(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_stranger, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    missing_group = uuid.uuid4()

    for gid in (sample_group.id, missing_group):
        for method, path in (
            ("GET", f"/api/v1/groups/{gid}/balances"),
            ("GET", f"/api/v1/groups/{gid}/balances/simplified"),
            ("GET", f"/api/v1/groups/{gid}/settlements"),
        ):
            resp = await client.request(method, path, headers=auth_headers_stranger)
            assert resp.status_code == 404, path
            assert resp.json()["code"] == "GROUP_NOT_FOUND"
            assert str(user_a.id) not in resp.text

        resp = await client.post(
            f"/api/v1/groups/{gid}/settlements",
            json={"payer_id": str(user_b.id), "payee_id": str(user_a.id), "amount_paise": 100},
            headers=auth_headers_stranger,
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "GROUP_NOT_FOUND"

    assert len(expense_db.settlements) == 0


@pytest.mark.asyncio
async def test_unauthenticated_requests_rejected(client, sample_group):
    for method, path in (
        ("GET", f"/api/v1/groups/{sample_group.id}/balances"),
        ("GET", f"/api/v1/groups/{sample_group.id}/balances/simplified"),
        ("GET", f"/api/v1/groups/{sample_group.id}/settlements"),
        ("POST", f"/api/v1/groups/{sample_group.id}/settlements"),
    ):
        resp = await client.request(method, path)
        assert resp.status_code == 401, path


# ==============================================================================
# Idempotency
# ==============================================================================


@pytest.mark.asyncio
async def test_idempotent_retry_creates_one_row(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    key = str(uuid.uuid4())

    first = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, full=True, key=key)
    assert first.status_code == 201, first.text
    assert "x-idempotent-replay" not in first.headers

    # Retry after the debt is already settled still returns the original result.
    second = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, full=True, key=key)
    assert second.status_code == 201, second.text
    assert second.headers.get("x-idempotent-replay") == "true"
    assert second.json() == first.json()

    assert len(expense_db.settlements) == 1
    assert len([a for a in expense_db.audit_events.values() if a.entity_type == "settlement"]) == 1

    bal = await get_balances(client, sample_group, auth_headers_user_a)
    assert bal["net_positions"][str(user_b.id)] == 0

    # Same key with a different payload is a conflict.
    conflict = await settle(
        client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=500, key=key
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(expense_db.settlements) == 1


# ==============================================================================
# Transaction and audit
# ==============================================================================


@pytest.mark.asyncio
async def test_settlement_and_audit_event_written_together(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)

    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=25000)
    assert resp.status_code == 201
    stl_id = uuid.UUID(resp.json()["id"])

    audits = [a for a in expense_db.audit_events.values() if a.entity_type == "settlement"]
    assert len(audits) == 1
    assert audits[0].entity_id == stl_id
    assert audits[0].action == "settlement_created"
    assert audits[0].actor_id == user_b.id


@pytest.mark.asyncio
async def test_settlement_rolls_back_completely_on_database_failure(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, fake_session, expense_db,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    audits_before = len(expense_db.audit_events)

    fake_session.fail_on_commit = True
    with pytest.raises(RuntimeError, match="Simulated database failure"):
        await settle(
            client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=1000, key="k-1"
        )

    assert len(expense_db.settlements) == 0
    assert len(expense_db.audit_events) == audits_before
    assert len(expense_db.idempotency_records) == 0


# ==============================================================================
# Listing
# ==============================================================================


@pytest.mark.asyncio
async def test_list_settlements_newest_first_with_mobile_fields(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b, auth_headers_user_c,
):
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    r1 = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=1000,
                      settlement_date="2026-11-10")
    r2 = await settle(client, sample_group, auth_headers_user_c, user_c, user_a, amount_paise=2000,
                      settlement_date="2026-11-12", payment_method="cash", notes="Paid in cash")
    assert r1.status_code == 201 and r2.status_code == 201

    resp = await client.get(f"/api/v1/groups/{sample_group.id}/settlements", headers=auth_headers_user_b)
    assert resp.status_code == 200
    items = resp.json()
    assert [i["id"] for i in items] == [r2.json()["id"], r1.json()["id"]]
    newest = items[0]
    # Fields read by mobile/src/features/balances/services/balancesApi.ts
    for field in (
        "id", "group_id", "payer_id", "payee_id", "amount_paise", "status", "payment_method",
        "notes", "settlement_date", "is_partial", "created_at", "updated_at",
    ):
        assert field in newest
    assert newest["settlement_date"] == "2026-11-12"
    assert newest["payment_method"] == "cash"
    assert newest["amount_paise"] == 2000


@pytest.mark.asyncio
async def test_balances_list_every_active_member_even_with_zero(
    client, sample_group, user_a, user_b, user_c, auth_headers_user_a,
):
    bal = await get_balances(client, sample_group, auth_headers_user_a)
    assert bal["net_positions"] == {str(user_a.id): 0, str(user_b.id): 0, str(user_c.id): 0}
    assert {m["status"] for m in bal["members"]} == {"settled"}
    assert bal["suggested_transfers"] == []
    assert bal["total_debt_paise"] == 0


# ==============================================================================
# Zero-sum and agreement with the ledger engine
# ==============================================================================


@pytest.mark.asyncio
async def test_net_positions_sum_to_zero_and_match_ledger_after_settlements(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b, auth_headers_user_c, expense_db,
):
    """API figures equal net_positions()/simplify() run directly on the stored rows."""
    rng = random.Random(20261118)
    users = [(user_a, auth_headers_user_a), (user_b, auth_headers_user_b), (user_c, auth_headers_user_c)]

    for _ in range(6):
        payer, headers = rng.choice(users)
        others = [u for u, _ in users if u.id != payer.id]
        participants = [payer] + rng.sample(others, rng.randint(1, 2))
        await add_expense(
            client, sample_group, sample_category, headers, rng.randint(1, 500000), participants
        )

        bal = await get_balances(client, sample_group, auth_headers_user_a)
        transfers = bal["suggested_transfers"]
        if transfers:
            t = transfers[0]
            debtor = next((u, h) for u, h in users if str(u.id) == t["from_user"])
            creditor = next(u for u, _ in users if str(u.id) == t["to_user"])
            amount = rng.randint(1, t["amount_paise"])
            resp = await settle(client, sample_group, debtor[1], debtor[0], creditor, amount_paise=amount)
            assert resp.status_code == 201, resp.text

        bal = await get_balances(client, sample_group, auth_headers_user_a)
        assert sum(bal["net_positions"].values()) == 0
        expected = ledger_from_fake_db(expense_db, sample_group.id)
        for uid in bal["net_positions"]:
            assert bal["net_positions"][uid] == expected.get(uid, 0)
        assert bal["suggested_transfers"] == [t.model_dump() for t in simplify(expected)]

    assert len(expense_db.settlements) >= 1
    # Settlements never create expense rows.
    assert len(expense_db.expenses) == 6
    assert all(isinstance(s.amount_paise, int) for s in expense_db.settlements.values())
    assert all(s.created_at <= datetime.now(UTC) for s in expense_db.settlements.values())


# ==============================================================================
# Settlements count in T-34 edit/delete balances (audit snapshots, response)
# ==============================================================================


def audit_payload(db, action):
    events = [a for a in db.audit_events.values() if a.action == action]
    assert len(events) == 1, action
    return json.loads(events[0].before_after)


@pytest.mark.asyncio
async def test_edit_after_settlement_audit_balances_include_settlement(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    """A pays ₹3,000 for A, B, C; B repays ₹1,000; A then edits the bill to ₹6,000."""
    exp = await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    # The real database fills version=1 on insert (server default); the fake does not.
    expense_db.expenses[uuid.UUID(exp["id"])].version = 1
    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=100000)
    assert resp.status_code == 201

    edit = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{exp['id']}",
        json={"amount_paise": 600000, "version": 1},
        headers=auth_headers_user_a,
    )
    assert edit.status_code == 200, edit.text

    payload = audit_payload(expense_db, "expense_updated")
    # Before: expense (A +200000, B -100000, C -100000) plus B's 100000 repayment.
    assert payload["before"]["balances"] == {
        str(user_a.id): 100000,
        str(user_b.id): 0,
        str(user_c.id): -100000,
    }
    # After: shares 200000 each (A +400000, B -200000, C -200000) plus the repayment.
    assert payload["after"]["balances"] == {
        str(user_a.id): 300000,
        str(user_b.id): -100000,
        str(user_c.id): -200000,
    }
    assert sum(payload["after"]["balances"].values()) == 0

    bal = await get_balances(client, sample_group, auth_headers_user_a)
    assert bal["net_positions"] == payload["after"]["balances"]


@pytest.mark.asyncio
async def test_delete_after_settlement_audit_balances_include_settlement(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b, expense_db,
):
    """Deleting the bill after B repaid leaves only the repayment: A now owes B."""
    exp = await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    # The real database fills version=1 on insert (server default); the fake does not.
    expense_db.expenses[uuid.UUID(exp["id"])].version = 1
    resp = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=100000)
    assert resp.status_code == 201

    delete = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{exp['id']}?version=1",
        headers=auth_headers_user_a,
    )
    assert delete.status_code == 200, delete.text

    payload = audit_payload(expense_db, "expense_deleted")
    assert payload["before"]["balances"] == {
        str(user_a.id): 100000,
        str(user_b.id): 0,
        str(user_c.id): -100000,
    }
    expected_after = {str(user_a.id): -100000, str(user_b.id): 100000}
    assert payload["after"]["balances"] == expected_after

    body = delete.json()
    assert body["netPositions"] == expected_after
    assert body["suggestedTransfers"] == [
        {"from_user": str(user_a.id), "to_user": str(user_b.id), "amount_paise": 100000}
    ]

    bal = await get_balances(client, sample_group, auth_headers_user_a)
    assert bal["net_positions"] == {**expected_after, str(user_c.id): 0}


# ==============================================================================
# Group history shows settlements (FR-17)
# ==============================================================================


@pytest.mark.asyncio
async def test_group_history_includes_settlements_newest_first(
    client, sample_group, sample_category, user_a, user_b, user_c,
    auth_headers_user_a, auth_headers_user_b, auth_headers_user_c, expense_db,
):
    base = datetime.now(UTC)
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    for a in expense_db.audit_events.values():
        a.created_at = base - timedelta(minutes=3)

    r1 = await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=40000)
    assert r1.status_code == 201
    stl1 = uuid.UUID(r1.json()["id"])
    next(a for a in expense_db.audit_events.values() if a.entity_id == stl1).created_at = (
        base - timedelta(minutes=2)
    )
    r2 = await settle(client, sample_group, auth_headers_user_c, user_c, user_a, amount_paise=100000)
    assert r2.status_code == 201
    stl2 = uuid.UUID(r2.json()["id"])

    # A settlement in another group must not show up in this group's history.
    other_group = uuid.uuid4()
    expense_db.settlements[uuid.uuid4()] = Settlement(
        id=uuid.uuid4(), group_id=other_group, payer_id=user_b.id, payee_id=user_a.id,
        amount_paise=1, status="completed", settlement_date=base.date(),
        created_at=base, updated_at=base,
    )

    resp = await client.get(f"/api/v1/groups/{sample_group.id}/history", headers=auth_headers_user_b)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert [(i["entityType"], i["action"]) for i in items] == [
        ("settlement", "settlement_created"),
        ("settlement", "settlement_created"),
        ("expense", "expense_created"),
    ]
    assert [uuid.UUID(i["entityId"]) for i in items[:2]] == [stl2, stl1]
    assert items[0]["actorId"] == str(user_c.id)
    assert items[0]["groupId"] == str(sample_group.id)
    assert items[0]["beforeAfter"]["amount_paise"] == 100000
    assert items[1]["beforeAfter"]["is_partial"] is True


@pytest.mark.asyncio
async def test_group_history_access_rules_unchanged(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, auth_headers_stranger,
):
    """History keeps its existing rule: members only, non-members get 403."""
    await add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    assert (await settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=1)).status_code == 201

    resp = await client.get(f"/api/v1/groups/{sample_group.id}/history", headers=auth_headers_stranger)
    assert resp.status_code == 403
    assert resp.json()["code"] == "GROUP_ACCESS_DENIED"
    assert "settlement" not in resp.text

    unauth = await client.get(f"/api/v1/groups/{sample_group.id}/history")
    assert unauth.status_code == 401
