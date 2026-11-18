from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.expense import AuditEvent, Expense, ExpensePayment, ExpenseShare
from app.models.group import Group, GroupMember, GroupMemberRole, GroupMemberStatus
from app.models.settlement import Settlement
from app.models.user import User
from app.schemas.ledger import SplitMode, SuggestedTransfer
from app.schemas.shared_expense import (
    ExpensePaymentItem,
    ExpenseShareItem,
    SharedExpenseCreateRequest,
    SharedExpenseResponse,
    SharedExpenseUpdateRequest,
)
from app.services.group_service import check_group_membership, get_group_or_404
from app.services import settlement_service
from app.services.ledger import allocate, simplify
from app.services.notifications import notify_group_members


def format_shared_expense_response(
    expense: Expense,
    split_mode: Optional[str] = None,
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
        version=getattr(expense, "version", None) or 1,
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
    payments_map: Dict[str, int] = {}
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
    participant_ids: List[str] = []
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

        payment_records: List[ExpensePayment] = []
        for p_id_str, amt in payments_map.items():
            payment_rec = ExpensePayment(
                expense_id=expense.id,
                user_id=uuid.UUID(p_id_str),
                amount_paise=amt,
            )
            db.add(payment_rec)
            payment_records.append(payment_rec)

        share_records: List[ExpenseShare] = []
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

    # Notify active group members after transaction commits
    notify_group_members(
        group=group,
        actor_id=current_user.id,
        kind="group_expense_created",
        ref=str(expense.id),
        payload={
            "expense_id": str(expense.id),
            "group_id": str(group_id),
            "description": expense.description,
            "amount_paise": payload.amount_paise,
            "created_by": str(current_user.id),
        },
    )

    # Attach loaded collections for response formatting
    expense.payments = payment_records
    expense.shares = share_records
    return format_shared_expense_response(expense, split_mode=mode_str)


async def list_shared_expenses(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> List[SharedExpenseResponse]:
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


async def compute_group_net_positions(
    db: AsyncSession,
    group_id: uuid.UUID,
) -> Dict[str, int]:
    """Member net positions from all live group expenses and completed settlements.

    Delegates to settlement_service.compute_net_positions so balances are computed
    one way only (ledger.net_positions over expenses and settlements, US-20).
    """
    return await settlement_service.compute_net_positions(db, group_id)


async def get_shared_expense(
    db: AsyncSession,
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    current_user: User,
) -> SharedExpenseResponse:
    """Retrieve details of a single shared expense."""
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=False)

    result = await db.execute(
        select(Expense)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.shares),
        )
        .where(
            Expense.id == expense_id,
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Expense not found."},
        )
    return format_shared_expense_response(expense)


async def update_shared_expense(
    db: AsyncSession,
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    current_user: User,
    payload: SharedExpenseUpdateRequest,
    expected_version: Optional[int] = None,
) -> SharedExpenseResponse:
    """Atomically update a shared expense with optimistic concurrency and balance recalculation.

    Enforces that only the original expense creator or a group admin can edit.
    Recalculates group balances and records before-and-after audit logs in the same transaction.
    Dispatches notifications only after transaction commit.
    """
    # 1. Authorize caller is an active group member
    group = await get_group_or_404(db, group_id)
    caller_member = check_group_membership(group, current_user, require_admin=False)

    # 2. Fetch the existing expense
    result = await db.execute(
        select(Expense)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.shares),
        )
        .where(
            Expense.id == expense_id,
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Expense not found."},
        )

    # 3. Authorization check: creator or group admin only
    is_admin = (
        group.created_by == current_user.id
        or (
            caller_member.role == GroupMemberRole.ADMIN.value
            and caller_member.status == GroupMemberStatus.ACTIVE.value
        )
    )
    is_creator = (expense.user_id == current_user.id)
    if not is_creator:
        creator_stmt = select(AuditEvent.actor_id).where(
            AuditEvent.entity_id == expense.id,
            AuditEvent.action == "expense_created",
        )
        creator_res = await db.execute(creator_stmt)
        creator_actor_id = creator_res.scalar_one_or_none()
        if creator_actor_id is not None and creator_actor_id == current_user.id:
            is_creator = True

    if not (is_admin or is_creator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "Only the original expense creator or a group admin can edit this expense.",
            },
        )

    # 4. Optimistic locking / version check
    version_to_check = (
        expected_version if expected_version is not None else payload.version
    )
    if version_to_check is not None and expense.version != version_to_check:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "message": f"Version conflict. Expected version {version_to_check}, but record is currently version {expense.version}.",
            },
        )

    # 5. Validate category if updated
    new_category_id = (
        payload.category_id if payload.category_id is not None else expense.category_id
    )
    if payload.category_id is not None and payload.category_id != expense.category_id:
        category = await db.get(Category, payload.category_id)
        if not category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "CATEGORY_NOT_FOUND", "message": "Category not found."},
            )

    active_members_dict = {
        m.user_id: m for m in group.members if m.status == GroupMemberStatus.ACTIVE.value
    }
    if not active_members_dict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_ACTIVE_MEMBERS", "message": "Group has no active members."},
        )

    # 6. Reconcile updated expense fields
    new_amount = (
        payload.amount_paise if payload.amount_paise is not None else expense.amount_minor
    )
    new_description = (
        payload.description if payload.description is not None else expense.description
    )
    new_expense_date = (
        payload.expense_date if payload.expense_date is not None else expense.expense_date
    )
    new_notes = payload.notes if payload.notes is not None else expense.notes
    new_merchant = payload.merchant if payload.merchant is not None else expense.merchant
    new_payment_mode = (
        payload.payment_mode if payload.payment_mode is not None else expense.payment_mode
    )

    # 7. Resolve and validate payers
    payments_map: Dict[str, int] = {}
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

        if total_paid != new_amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "UNBALANCED_PAYMENTS",
                    "message": f"Total payments ({total_paid}) do not equal expense amount ({new_amount}).",
                },
            )
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
        payments_map[str(payload.paid_by_user_id)] = new_amount
        primary_payer_id = payload.paid_by_user_id
    else:
        # Preserve existing payments
        if len(expense.payments) == 1:
            existing_payer = expense.payments[0].user_id
            payments_map[str(existing_payer)] = new_amount
            primary_payer_id = existing_payer
        else:
            existing_total = sum(p.amount_paise for p in expense.payments)
            if existing_total != new_amount:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "UNBALANCED_PAYMENTS",
                        "message": f"Existing payments sum ({existing_total}) does not match new amount ({new_amount}). Explicit payments required.",
                    },
                )
            payments_map = {str(p.user_id): p.amount_paise for p in expense.payments}
            primary_payer_id = expense.user_id

    # 8. Resolve and validate participants
    participant_ids: List[str] = []
    if payload.participant_user_ids is not None:
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
        participant_ids = [str(s.user_id) for s in (expense.shares or [])]
        if not participant_ids:
            sorted_members = sorted(
                [m for m in group.members if m.status == GroupMemberStatus.ACTIVE.value],
                key=lambda m: (m.joined_at, str(m.user_id)),
            )
            participant_ids = [str(m.user_id) for m in sorted_members]

    # 9. Allocate updated shares using pure ledger engine
    new_split_mode = payload.split_mode
    if new_split_mode is None:
        if expense.shares:
            new_split_mode = expense.shares[0].rule
        else:
            new_split_mode = SplitMode.EQUAL

    new_split_weights = payload.split_weights
    if new_split_weights is None and payload.split_mode is None:
        existing_weights = {}
        for s in (expense.shares or []):
            if s.rule_value is not None:
                existing_weights[str(s.user_id)] = float(s.rule_value)
        if existing_weights:
            new_split_weights = existing_weights

    try:
        shares_map = allocate(
            amount_paise=new_amount,
            participants=participant_ids,
            split_mode=new_split_mode,
            weights=new_split_weights,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SPLIT", "message": str(e)},
        ) from e

    total_shares = sum(shares_map.values())
    if total_shares != new_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNBALANCED_SHARES",
                "message": f"Sum of shares ({total_shares}) does not match expense amount ({new_amount}).",
            },
        )

    # 10. Capture before-and-after snapshots and balances
    old_balances = await compute_group_net_positions(db, group_id)
    before_snapshot = {
        "group_id": str(group_id),
        "expense_id": str(expense.id),
        "amount_paise": expense.amount_minor,
        "description": expense.description,
        "category_id": str(expense.category_id),
        "expense_date": expense.expense_date.isoformat(),
        "split_mode": expense.shares[0].rule if expense.shares else "equal",
        "payments": {str(p.user_id): p.amount_paise for p in expense.payments},
        "shares": {str(s.user_id): s.amount_paise for s in expense.shares},
        "balances": old_balances,
    }

    mode_str = (
        new_split_mode.value
        if isinstance(new_split_mode, SplitMode)
        else str(new_split_mode)
    )
    now = datetime.now(UTC)
    new_version = expense.version + 1

    # 11. Atomic transaction: update Expense, rewrite payments & shares, compute new balances, write AuditEvent
    try:
        update_stmt = (
            update(Expense)
            .where(
                Expense.id == expense.id,
                Expense.version == expense.version,
                Expense.deleted_at.is_(None),
            )
            .values(
                user_id=primary_payer_id,
                category_id=new_category_id,
                amount_minor=new_amount,
                description=new_description,
                expense_date=new_expense_date,
                notes=new_notes,
                merchant=new_merchant,
                payment_mode=new_payment_mode,
                version=new_version,
                updated_at=now,
            )
        )
        update_res = await db.execute(update_stmt)
        if update_res.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "VERSION_CONFLICT",
                    "message": "Concurrent update detected. The record was modified by another request.",
                },
            )

        # Clear old payments and shares
        await db.execute(
            delete(ExpensePayment).where(ExpensePayment.expense_id == expense.id)
        )
        await db.execute(
            delete(ExpenseShare).where(ExpenseShare.expense_id == expense.id)
        )

        payment_records: List[ExpensePayment] = []
        for p_id_str, amt in payments_map.items():
            payment_rec = ExpensePayment(
                expense_id=expense.id,
                user_id=uuid.UUID(p_id_str),
                amount_paise=amt,
            )
            db.add(payment_rec)
            payment_records.append(payment_rec)

        share_records: List[ExpenseShare] = []
        for part_id_str, amt in shares_map.items():
            rule_val = None
            if new_split_weights and part_id_str in new_split_weights:
                try:
                    rule_val = float(new_split_weights[part_id_str])
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

        await db.flush()

        # Recalculate balances immediately in the same database transaction
        new_balances = await compute_group_net_positions(db, group_id)

        after_snapshot = {
            "group_id": str(group_id),
            "expense_id": str(expense.id),
            "amount_paise": new_amount,
            "description": new_description,
            "category_id": str(new_category_id),
            "expense_date": new_expense_date.isoformat(),
            "split_mode": mode_str,
            "payments": payments_map,
            "shares": shares_map,
            "balances": new_balances,
        }

        audit_event = AuditEvent(
            actor_id=current_user.id,
            entity_type="expense",
            entity_id=expense.id,
            action="expense_updated",
            before_after=json.dumps({"before": before_snapshot, "after": after_snapshot}),
        )
        db.add(audit_event)

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 12. Dispatch notification to all active group members ONLY after successful commit
    notify_group_members(
        group=group,
        actor_id=current_user.id,
        kind="group_expense_updated",
        ref=str(expense.id),
        payload={
            "expense_id": str(expense.id),
            "group_id": str(group_id),
            "description": new_description,
            "amount_paise": new_amount,
            "updated_by": str(current_user.id),
            "new_balances": new_balances,
        },
    )

    expense.user_id = primary_payer_id
    expense.category_id = new_category_id
    expense.amount_minor = new_amount
    expense.description = new_description
    expense.expense_date = new_expense_date
    expense.notes = new_notes
    expense.merchant = new_merchant
    expense.payment_mode = new_payment_mode
    expense.version = new_version
    expense.updated_at = now
    expense.payments = payment_records
    expense.shares = share_records

    return format_shared_expense_response(expense, split_mode=mode_str)


async def delete_shared_expense(
    db: AsyncSession,
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    current_user: User,
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Atomically soft-delete a shared expense with balance recalculation and audit preservation.

    Enforces creator or group admin permission.
    Recalculates group balances immediately within the transaction.
    Preserves audit history and dispatches notifications only after commit.
    """
    # 1. Authorize caller is an active group member
    group = await get_group_or_404(db, group_id)
    caller_member = check_group_membership(group, current_user, require_admin=False)

    # 2. Fetch the existing active expense
    result = await db.execute(
        select(Expense)
        .options(
            selectinload(Expense.payments),
            selectinload(Expense.shares),
        )
        .where(
            Expense.id == expense_id,
            Expense.group_id == group_id,
            Expense.deleted_at.is_(None),
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Expense not found."},
        )

    # 3. Check permissions: creator or group admin
    is_admin = (
        group.created_by == current_user.id
        or (
            caller_member.role == GroupMemberRole.ADMIN.value
            and caller_member.status == GroupMemberStatus.ACTIVE.value
        )
    )
    is_creator = (expense.user_id == current_user.id)
    if not is_creator:
        creator_stmt = select(AuditEvent.actor_id).where(
            AuditEvent.entity_id == expense.id,
            AuditEvent.action == "expense_created",
        )
        creator_res = await db.execute(creator_stmt)
        creator_actor_id = creator_res.scalar_one_or_none()
        if creator_actor_id is not None and creator_actor_id == current_user.id:
            is_creator = True

    if not (is_admin or is_creator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "Only the original expense creator or a group admin can delete this expense.",
            },
        )

    # 4. Check expected version if provided
    if expected_version is not None and expense.version != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "message": f"Version conflict. Expected version {expected_version}, but record is currently version {expense.version}.",
            },
        )

    old_balances = await compute_group_net_positions(db, group_id)
    before_snapshot = {
        "group_id": str(group_id),
        "expense_id": str(expense.id),
        "amount_paise": expense.amount_minor,
        "description": expense.description,
        "split_mode": expense.shares[0].rule if expense.shares else "equal",
        "payments": {str(p.user_id): p.amount_paise for p in expense.payments},
        "shares": {str(s.user_id): s.amount_paise for s in expense.shares},
        "balances": old_balances,
    }

    now = datetime.now(UTC)
    new_version = expense.version + 1

    try:
        delete_stmt = (
            update(Expense)
            .where(
                Expense.id == expense.id,
                Expense.version == expense.version,
                Expense.deleted_at.is_(None),
            )
            .values(
                deleted_at=now,
                version=new_version,
                updated_at=now,
            )
        )
        del_res = await db.execute(delete_stmt)
        if del_res.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "VERSION_CONFLICT",
                    "message": "Concurrent update detected. The record was modified by another request.",
                },
            )

        expense.deleted_at = now
        expense.version = new_version
        expense.updated_at = now

        await db.flush()

        # Recalculate group balances excluding soft-deleted expense
        new_balances = await compute_group_net_positions(db, group_id)
        new_transfers = simplify(new_balances)

        after_snapshot = {
            "group_id": str(group_id),
            "expense_id": str(expense.id),
            "deleted": True,
            "deleted_at": now.isoformat(),
            "balances": new_balances,
        }

        audit_event = AuditEvent(
            actor_id=current_user.id,
            entity_type="expense",
            entity_id=expense.id,
            action="expense_deleted",
            before_after=json.dumps({"before": before_snapshot, "after": after_snapshot}),
        )
        db.add(audit_event)

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # Notify all active members after commit
    notify_group_members(
        group=group,
        actor_id=current_user.id,
        kind="group_expense_deleted",
        ref=str(expense.id),
        payload={
            "expense_id": str(expense.id),
            "group_id": str(group_id),
            "description": expense.description,
            "amount_paise": expense.amount_minor,
            "deleted_by": str(current_user.id),
            "new_balances": new_balances,
        },
    )

    return {
        "message": "Shared expense deleted successfully.",
        "expense_id": str(expense.id),
        "group_id": str(group_id),
        "deleted": True,
        "version": new_version,
        "net_positions": new_balances,
        "suggested_transfers": [t.model_dump() for t in new_transfers],
    }


async def get_group_history(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> List[Dict[str, Any]]:
    """Retrieve group transaction and audit history."""
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=False)

    stmt = (
        select(AuditEvent)
        .outerjoin(Expense, AuditEvent.entity_id == Expense.id)
        .outerjoin(Settlement, AuditEvent.entity_id == Settlement.id)
        .where(
            or_(
                Expense.group_id == group_id,
                AuditEvent.entity_id == group_id,
                Settlement.group_id == group_id,
            )
        )
        .order_by(AuditEvent.created_at.desc())
    )
    result = await db.execute(stmt)
    audit_events = result.scalars().all()
    history_items = []
    for evt in audit_events:
        before_after_parsed = None
        if evt.before_after:
            try:
                before_after_parsed = json.loads(evt.before_after)
            except Exception:
                before_after_parsed = {"raw": evt.before_after}
        history_items.append({
            "id": evt.id,
            "group_id": group_id,
            "entity_type": evt.entity_type,
            "entity_id": evt.entity_id,
            "action": evt.action,
            "actor_id": evt.actor_id,
            "before_after": before_after_parsed,
            "created_at": evt.created_at,
        })
    return history_items


