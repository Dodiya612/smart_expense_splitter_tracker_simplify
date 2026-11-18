"""Balances and settlements service (US-20 / T-32).

Rules (ledger.md sections 4 and 6):
- Every balance figure comes from the pure ledger engine
  (app.services.ledger.net_positions / simplify). This module only loads
  records and converts them to ledger inputs; it does no balance arithmetic
  of its own beyond reading the engine's output.
- Money is whole paise (int).
- A settlement adjusts net positions only. It never creates an Expense row,
  so it is never counted as spending or income.
- Strangers get 404 (GroupPolicy.authorize_member_or_404).
- A settlement row, its audit event and its idempotency record are written
  in one transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import GroupPolicy
from app.models.expense import AuditEvent, Expense
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus
from app.models.idempotency import IdempotencyRecord
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.ledger import ExpenseRecord, SettlementRecord
from app.schemas.settlement import (
    GroupBalancesResponse,
    MemberBalanceItem,
    SettlementCreateRequest,
    SettlementResponse,
    SimplifiedRepaymentsResponse,
    TransferItem,
)
from app.services.group_service import get_group_or_404
from app.services.ledger import net_positions, simplify

logger = logging.getLogger(__name__)

# Asia/Kolkata has no daylight saving time, so a fixed offset is exact.
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

SETTLEMENT_STATUS_COMPLETED = "completed"


def utcnow() -> datetime:
    return datetime.now(UTC)


def today_in_kolkata() -> date:
    return datetime.now(IST).date()


# ---------------------------------------------------------------------------
# Loading and authorization
# ---------------------------------------------------------------------------


def _active_members(group: Group) -> dict[uuid.UUID, GroupMember]:
    return {
        m.user_id: m for m in group.members if m.status == GroupMemberStatus.ACTIVE.value
    }


async def load_group_for_member(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> tuple[Group, GroupMember]:
    """Load the group through the policy module. Missing group or stranger -> 404."""
    group = await get_group_or_404(db, group_id)
    active = _active_members(group)
    GroupPolicy.authorize_member_or_404(current_user, group.id, set(active.keys()))
    return group, active[current_user.id]


async def compute_net_positions(
    db: AsyncSession,
    group_id: uuid.UUID,
) -> dict[str, int]:
    """Net position per member from all live group expenses and completed settlements.

    The arithmetic is done only by ledger.net_positions().
    """
    exp_res = await db.execute(
        select(Expense)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.shares),
        )
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
        )
    )
    expense_records: list[ExpenseRecord | dict[str, Any]] = [
        ExpenseRecord(
            expense_id=str(exp.id),
            description=exp.description,
            amount_paise=exp.amount_minor,
            payments={str(p.user_id): p.amount_paise for p in exp.payments},
            shares={str(s.user_id): s.amount_paise for s in exp.shares},
        )
        for exp in exp_res.scalars().all()
    ]

    stl_res = await db.execute(
        select(Settlement)
        .where(
            Settlement.group_id == group_id,
            Settlement.status == SETTLEMENT_STATUS_COMPLETED,
        )
        .order_by(Settlement.created_at.asc())
    )
    settlement_records: list[SettlementRecord | dict[str, Any]] = [
        SettlementRecord(
            settlement_id=str(stl.id),
            from_user=str(stl.payer_id),
            to_user=str(stl.payee_id),
            amount_paise=stl.amount_paise,
        )
        for stl in stl_res.scalars().all()
    ]

    return net_positions(expense_records, settlement_records)


def _transfers(balances: dict[str, int]) -> list[TransferItem]:
    return [
        TransferItem(from_user=t.from_user, to_user=t.to_user, amount_paise=t.amount_paise)
        for t in simplify(balances)
    ]


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


async def get_group_balances(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> GroupBalancesResponse:
    """Net positions (incl. settlements), member summaries and simplified transfers."""
    group, _ = await load_group_for_member(db, group_id, current_user)
    balances = await compute_net_positions(db, group_id)

    # Every active member is listed, even with a zero balance. Former members
    # who still have a non-zero position stay listed so money never disappears.
    for uid in _active_members(group):
        balances.setdefault(str(uid), 0)

    members: list[MemberBalanceItem] = []
    for uid_str, bal in sorted(balances.items()):
        if bal > 0:
            members.append(
                MemberBalanceItem(
                    user_id=uuid.UUID(uid_str),
                    net_balance_paise=bal,
                    owes_paise=0,
                    receives_paise=bal,
                    status="creditor",
                )
            )
        elif bal < 0:
            members.append(
                MemberBalanceItem(
                    user_id=uuid.UUID(uid_str),
                    net_balance_paise=bal,
                    owes_paise=-bal,
                    receives_paise=0,
                    status="debtor",
                )
            )
        else:
            members.append(
                MemberBalanceItem(
                    user_id=uuid.UUID(uid_str),
                    net_balance_paise=0,
                    owes_paise=0,
                    receives_paise=0,
                    status="settled",
                )
            )

    return GroupBalancesResponse(
        group_id=group_id,
        net_positions=balances,
        suggested_transfers=_transfers(balances),
        members=members,
        total_debt_paise=sum(m.receives_paise for m in members),
        currency="INR",
    )


async def get_simplified_repayments(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> SimplifiedRepaymentsResponse:
    """Greedy 'who pays whom' suggestions from ledger.simplify()."""
    await load_group_for_member(db, group_id, current_user)
    balances = await compute_net_positions(db, group_id)
    transfers = _transfers(balances)
    return SimplifiedRepaymentsResponse(
        group_id=group_id,
        suggested_transfers=transfers,
        total_transfers=len(transfers),
        total_amount_paise=sum(t.amount_paise for t in transfers),
    )


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------


def format_settlement_response(
    settlement: Settlement,
    is_partial: bool = False,
    remaining_debt_paise: int | None = None,
) -> SettlementResponse:
    return SettlementResponse(
        id=settlement.id,
        group_id=settlement.group_id,
        payer_id=settlement.payer_id,
        payee_id=settlement.payee_id,
        amount_paise=settlement.amount_paise,
        status=settlement.status,
        payment_method=settlement.payment_method,
        notes=settlement.notes,
        settlement_date=settlement.settlement_date,
        is_partial=is_partial,
        remaining_debt_paise=remaining_debt_paise,
        created_at=settlement.created_at,
        updated_at=settlement.updated_at,
    )


def compute_settlement_payload_hash(
    user_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: SettlementCreateRequest,
) -> str:
    """Deterministic SHA-256 of the settlement request (same approach as expenses)."""
    canonical = {
        "kind": "settlement",
        "user_id": str(user_id),
        "group_id": str(group_id),
        "payer_id": str(payload.payer_id),
        "payee_id": str(payload.payee_id),
        "amount_paise": payload.amount_paise,
        "is_full_settlement": payload.is_full_settlement,
        "payment_method": payload.payment_method,
        "notes": payload.notes,
        "settlement_date": payload.settlement_date.isoformat() if payload.settlement_date else None,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()


def _idempotency_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key has already been used with a different request payload.",
        },
    )


async def _replay_idempotent(
    db: AsyncSession,
    user_id: uuid.UUID,
    group_id: uuid.UUID,
    idempotency_key: str,
    request_hash: str,
) -> SettlementResponse | None:
    """Return the stored response for a repeated key, raise 409 on a different payload."""
    idem_res = await db.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.key == idempotency_key,
        )
    )
    record = idem_res.scalar_one_or_none()
    if record is None:
        return None
    if record.request_hash != request_hash:
        raise _idempotency_conflict()
    try:
        return SettlementResponse.model_validate(json.loads(record.response_body))
    except ValueError as exc:
        logger.warning("Failed to parse stored settlement idempotency body: %s", exc)
    if record.resource_id is not None:
        stl_res = await db.execute(
            select(Settlement).where(
                Settlement.id == record.resource_id,
                Settlement.group_id == group_id,
            )
        )
        stored = stl_res.scalar_one_or_none()
        if stored is not None:
            return format_settlement_response(stored)
    return None


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "message": message},
    )


async def create_settlement(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
    payload: SettlementCreateRequest,
    idempotency_key: str | None = None,
) -> tuple[SettlementResponse, bool]:
    """Record a full or partial settlement. Returns (response, is_replay).

    Validation:
    - Caller is an active member (else 404); caller is the payer, the payee or a
      group admin (else 403).
    - Payer and payee are different, active members of the group.
    - The payer owes money (net position < 0) and the payee is owed money
      (net position > 0). What the payer can settle with the payee is
      min(-NP_payer, NP_payee); a settlement cannot exceed it.
    """
    group, caller_member = await load_group_for_member(db, group_id, current_user)

    request_hash: str | None = None
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 255:
            raise _bad_request(
                "INVALID_IDEMPOTENCY_KEY",
                "Idempotency-Key must be between 1 and 255 characters.",
            )
        request_hash = compute_settlement_payload_hash(current_user.id, group_id, payload)
        replay = await _replay_idempotent(
            db, current_user.id, group_id, idempotency_key, request_hash
        )
        if replay is not None:
            return replay, True

    payer_id = payload.payer_id
    payee_id = payload.payee_id

    if payer_id == payee_id:
        raise _bad_request(
            "SELF_SETTLEMENT_PROHIBITED", "Payer and payee cannot be the same member."
        )

    active = _active_members(group)
    if payer_id not in active:
        raise _bad_request("PAYER_NOT_IN_GROUP", "Payer is not an active member of this group.")
    if payee_id not in active:
        raise _bad_request("PAYEE_NOT_IN_GROUP", "Payee is not an active member of this group.")

    is_admin = caller_member.role == GroupMemberRole.ADMIN.value
    if current_user.id not in (payer_id, payee_id) and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SETTLEMENT_NOT_ALLOWED",
                "message": "Only the payer, the payee or a group admin may record this settlement.",
            },
        )

    # Serialise settlement creation per group so two concurrent requests cannot
    # both pass the ceiling check below (lock is released on commit/rollback).
    await db.execute(select(Group.id).where(Group.id == group_id).with_for_update())

    balances = await compute_net_positions(db, group_id)
    payer_np = balances.get(str(payer_id), 0)
    payee_np = balances.get(str(payee_id), 0)

    if payer_np >= 0:
        raise _bad_request(
            "PAYER_NOT_DEBTOR", "Payer does not owe anything in this group."
        )
    if payee_np <= 0:
        raise _bad_request(
            "PAYEE_NOT_CREDITOR", "Payee is not owed anything in this group."
        )

    outstanding = min(-payer_np, payee_np)

    if payload.is_full_settlement:
        if payload.amount_paise is not None and payload.amount_paise != outstanding:
            raise _bad_request(
                "AMOUNT_MISMATCH",
                f"Full settlement is {outstanding} paise, but amount_paise was "
                f"{payload.amount_paise}. Refresh balances and try again.",
            )
        amount = outstanding
    else:
        if payload.amount_paise is None:
            raise _bad_request(
                "AMOUNT_REQUIRED", "amount_paise is required unless is_full_settlement is true."
            )
        amount = payload.amount_paise

    if amount > outstanding:
        raise _bad_request(
            "AMOUNT_EXCEEDS_OUTSTANDING",
            f"Settlement amount ({amount} paise) exceeds what the payer owes the "
            f"payee ({outstanding} paise).",
        )

    remaining = outstanding - amount
    is_partial = remaining > 0
    now = utcnow()

    settlement = Settlement(
        id=uuid.uuid4(),
        group_id=group_id,
        payer_id=payer_id,
        payee_id=payee_id,
        amount_paise=amount,
        status=SETTLEMENT_STATUS_COMPLETED,
        payment_method=payload.payment_method,
        notes=payload.notes,
        settlement_date=payload.settlement_date or today_in_kolkata(),
        created_at=now,
        updated_at=now,
    )
    response = format_settlement_response(
        settlement, is_partial=is_partial, remaining_debt_paise=remaining
    )

    db.add(settlement)
    db.add(
        AuditEvent(
            id=uuid.uuid4(),
            actor_id=current_user.id,
            entity_type="settlement",
            entity_id=settlement.id,
            action="settlement_created",
            before_after=json.dumps(
                {
                    "group_id": str(group_id),
                    "payer_id": str(payer_id),
                    "payee_id": str(payee_id),
                    "amount_paise": amount,
                    "is_partial": is_partial,
                    "remaining_debt_paise": remaining,
                }
            ),
            created_at=now,
        )
    )
    if idempotency_key and request_hash:
        db.add(
            IdempotencyRecord(
                id=uuid.uuid4(),
                user_id=current_user.id,
                key=idempotency_key,
                request_hash=request_hash,
                response_code=status.HTTP_201_CREATED,
                response_body=json.dumps(response.model_dump(mode="json")),
                resource_id=settlement.id,
                created_at=now,
            )
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Concurrent retry with the same key: return the winner's response.
        if idempotency_key and request_hash:
            replay = await _replay_idempotent(
                db, current_user.id, group_id, idempotency_key, request_hash
            )
            if replay is not None:
                return replay, True
        raise _bad_request(
            "INTEGRITY_ERROR",
            "Could not record settlement due to a database constraint violation.",
        ) from exc
    except Exception:
        await db.rollback()
        raise

    return response, False


async def list_settlements(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> list[SettlementResponse]:
    """All settlements of the group, newest first."""
    await load_group_for_member(db, group_id, current_user)
    result = await db.execute(
        select(Settlement)
        .where(Settlement.group_id == group_id)
        .order_by(Settlement.settlement_date.desc(), Settlement.created_at.desc())
    )
    return [format_settlement_response(s) for s in result.scalars().all()]
