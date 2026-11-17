from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.expense import AuditEvent, Expense, ExpensePayment, ExpenseShare
from app.models.group import GroupMemberStatus
from app.models.user import User
from app.schemas.ledger import SplitMode
from app.schemas.shared_expense import (
    ExpensePaymentItem,
    ExpenseShareItem,
    SharedExpenseCreateRequest,
    SharedExpenseResponse,
)
from app.services.group_service import check_group_membership, get_group_or_404
from app.services.ledger import allocate


def format_shared_expense_response(
    expense: Expense,
    split_mode: str | None = None,
) -> SharedExpenseResponse:
    """Format an Expense entity into a SharedExpenseResponse DTO."""
    payments_dto = [
        ExpensePaymentItem(user_id=p.user_id, amount_paise=p.amount_paise)
        for p in (expense.payments or [])
    ]
    shares_dto = [
        ExpenseShareItem(
            user_id=s.user_id,
            amount_paise=s.amount_paise,
            rule=s.rule,
            rule_value=float(s.rule_value) if s.rule_value is not None else None,
        )
        for s in (expense.shares or [])
    ]

    inferred_split_mode = split_mode
    if not inferred_split_mode and expense.shares:
        inferred_split_mode = expense.shares[0].rule

    return SharedExpenseResponse(
        id=expense.id,
        group_id=expense.group_id,  # type: ignore[arg-type]
        user_id=expense.user_id,
        category_id=expense.category_id,
        amount_paise=expense.amount_minor,
        amount_minor=expense.amount_minor,
        description=expense.description,
        expense_date=expense.expense_date,
        notes=expense.notes,
        merchant=expense.merchant,
        payment_mode=expense.payment_mode,
        split_mode=inferred_split_mode or "equal",
        payments=payments_dto,
        shares=shares_dto,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


async def create_shared_expense(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
    payload: SharedExpenseCreateRequest,
) -> SharedExpenseResponse:
    """Create a shared expense in an existing group atomically.

    Integrates with the pure ledger engine to calculate and validate participant shares.
    Ensures expense, payments, shares, and audit records are committed together in one transaction.
    """
    # 1. Authorize caller is an active group member
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=False)

    # 2. Check category exists
    category = await db.get(Category, payload.category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found."},
        )

    # 3. Active members of group
    active_members_dict = {
        m.user_id: m for m in group.members if m.status == GroupMemberStatus.ACTIVE.value
    }
    if not active_members_dict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_ACTIVE_MEMBERS", "message": "Group has no active members."},
        )

    # 4. Resolve and validate payers
    payments_map: dict[str, int] = {}
    if payload.payments:
        if not isinstance(payload.payments, dict) or len(payload.payments) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_PAYMENTS", "message": "Payments map cannot be empty."},
            )
        total_paid = 0
        for p_id_str, amt in payload.payments.items():
            try:
                p_uuid = uuid.UUID(str(p_id_str))
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_PAYER", "message": f"Invalid payer UUID '{p_id_str}'."},
                )
            if p_uuid not in active_members_dict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "PAYER_NOT_MEMBER",
                        "message": f"Payer '{p_id_str}' is not an active member of this group.",
                    },
                )
            if amt <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"code": "INVALID_PAYMENT_AMOUNT", "message": "Payment amount must be greater than zero."},
                )
            payments_map[str(p_uuid)] = amt
            total_paid += amt

        if total_paid != payload.amount_paise:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "UNBALANCED_PAYMENTS",
                    "message": f"Total payments ({total_paid}) do not equal expense amount ({payload.amount_paise}).",
                },
            )
        # Select primary payer: the payer with the highest contribution
        primary_payer_id = uuid.UUID(max(payments_map, key=lambda k: payments_map[k]))
    elif payload.paid_by_user_id:
        if payload.paid_by_user_id not in active_members_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PAYER_NOT_MEMBER",
                    "message": f"Payer '{payload.paid_by_user_id}' is not an active member of this group.",
                },
            )
        payments_map[str(payload.paid_by_user_id)] = payload.amount_paise
        primary_payer_id = payload.paid_by_user_id
    else:
        # Default payer is current user
        if current_user.id not in active_members_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "PAYER_NOT_MEMBER", "message": "Current user is not an active member of this group."},
            )
        payments_map[str(current_user.id)] = payload.amount_paise
        primary_payer_id = current_user.id

    # 5. Resolve and validate participants
    participant_ids: list[str] = []
    if payload.participant_user_ids:
        if len(payload.participant_user_ids) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_PARTICIPANTS", "message": "Participant list cannot be empty."},
            )
        if len(set(payload.participant_user_ids)) != len(payload.participant_user_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "DUPLICATE_PARTICIPANTS", "message": "Participant list contains duplicate users."},
            )
        for part_id in payload.participant_user_ids:
            if part_id not in active_members_dict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "PARTICIPANT_NOT_MEMBER",
                        "message": f"Participant '{part_id}' is not an active member of this group.",
                    },
                )
            participant_ids.append(str(part_id))
    else:
        # Default to all active members sorted by joined_at and user_id for deterministic tie-breaking
        sorted_members = sorted(
            [m for m in group.members if m.status == GroupMemberStatus.ACTIVE.value],
            key=lambda m: (m.joined_at, str(m.user_id)),
        )
        participant_ids = [str(m.user_id) for m in sorted_members]

    # 6. Allocate shares using the pure ledger engine
    try:
        shares_map = allocate(
            amount_paise=payload.amount_paise,
            participants=participant_ids,
            split_mode=payload.split_mode,
            weights=payload.split_weights,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SPLIT", "message": str(e)},
        ) from e

    # Invariant: sum of shares must strictly equal amount_paise
    total_shares = sum(shares_map.values())
    if total_shares != payload.amount_paise:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNBALANCED_SHARES",
                "message": f"Sum of shares ({total_shares}) does not match expense amount ({payload.amount_paise}).",
            },
        )

    # 7. Atomic transaction: Expense, ExpensePayment, ExpenseShare, AuditEvent
    mode_str = (
        payload.split_mode.value
        if isinstance(payload.split_mode, SplitMode)
        else str(payload.split_mode)
    )

    try:
        expense = Expense(
            group_id=group_id,
            user_id=primary_payer_id,
            category_id=payload.category_id,
            amount_minor=payload.amount_paise,
            description=payload.description,
            expense_date=payload.expense_date,
            notes=payload.notes,
            merchant=payload.merchant,
            payment_mode=payload.payment_mode,
        )
        db.add(expense)
        await db.flush()

        payment_records: list[ExpensePayment] = []
        for p_id_str, amt in payments_map.items():
            payment_rec = ExpensePayment(
                expense_id=expense.id,
                user_id=uuid.UUID(p_id_str),
                amount_paise=amt,
            )
            db.add(payment_rec)
            payment_records.append(payment_rec)

        share_records: list[ExpenseShare] = []
        for part_id_str, amt in shares_map.items():
            rule_val = None
            if payload.split_weights and part_id_str in payload.split_weights:
                try:
                    rule_val = float(payload.split_weights[part_id_str])
                except (ValueError, TypeError):
                    rule_val = None
            share_rec = ExpenseShare(
                expense_id=expense.id,
                user_id=uuid.UUID(part_id_str),
                amount_paise=amt,
                rule=mode_str,
                rule_value=rule_val,
            )
            db.add(share_rec)
            share_records.append(share_rec)

        audit_snapshot = {
            "group_id": str(group_id),
            "expense_id": str(expense.id),
            "amount_paise": payload.amount_paise,
            "description": payload.description,
            "split_mode": mode_str,
            "payments": payments_map,
            "shares": shares_map,
        }
        audit_event = AuditEvent(
            actor_id=current_user.id,
            entity_type="expense",
            entity_id=expense.id,
            action="expense_created",
            before_after=json.dumps(audit_snapshot),
        )
        db.add(audit_event)

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # Attach loaded collections for response formatting
    expense.payments = payment_records
    expense.shares = share_records
    return format_shared_expense_response(expense, split_mode=mode_str)


async def list_shared_expenses(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> list[SharedExpenseResponse]:
    """List all non-deleted shared expenses for a group in reverse chronological order."""
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=False)

    result = await db.execute(
        select(Expense)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.shares),
        )
        .where(
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
        )
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
    )
    expenses = result.scalars().all()
    return [format_shared_expense_response(e) for e in expenses]


async def get_group_balances(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> Any:
    """Calculate dynamic net balances and suggested settlement transfers for a group.

    Integrates with the pure ledger engine net_positions() and simplify(), accounting
    for shared expenses and all completed repayments/settlements.
    """
    from app.services import settlement_service

    return await settlement_service.calculate_group_balances(db, group_id, current_user)

