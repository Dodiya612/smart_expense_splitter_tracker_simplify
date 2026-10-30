import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.expense import Expense
from app.models.idempotency import IdempotencyRecord
from app.schemas.expense import ExpenseCreate, ExpenseResponse, ExpenseUpdate

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def compute_payload_hash(user_id: uuid.UUID, data: ExpenseCreate) -> str:
    """Compute a deterministic SHA-256 hash of the expense creation payload."""
    canonical_dict = {
        "user_id": str(user_id),
        "amount_minor": data.amount_minor,
        "description": data.description,
        "category_id": str(data.category_id),
        "expense_date": data.expense_date.isoformat() if data.expense_date else None,
        "notes": data.notes,
        "merchant": data.merchant,
        "payment_mode": data.payment_mode,
        "receipt_id": str(data.receipt_id) if data.receipt_id else None,
    }
    payload_str = json.dumps(canonical_dict, sort_keys=True)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


async def validate_category_ownership(
    db: AsyncSession,
    user_id: uuid.UUID,
    category_id: uuid.UUID,
) -> Category:
    """
    Ensure the requested category exists and is either:
    1. A default system category (is_default == True), or
    2. Owned by the authenticated user (owner_id == user_id).
    Raises HTTP 400 with INVALID_CATEGORY if invalid.
    """
    stmt = select(Category).where(
        Category.id == category_id,
        (Category.is_default == True) | (Category.owner_id == user_id),
    )
    result = await db.execute(stmt)
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_CATEGORY",
                "message": f"Category '{category_id}' does not exist or is not accessible.",
            },
        )
    return category


async def create_expense(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: ExpenseCreate,
    idempotency_key: str | None = None,
) -> tuple[Expense, bool]:
    """
    Create a new personal expense record for the authenticated user.
    If idempotency_key is provided:
      - Valid duplicate requests return the existing expense record (is_cached=True).
      - Reusing the key with a different payload returns HTTP 409 Conflict.
    Returns:
      (Expense, is_cached: bool)
    """
    # 1. Validate category accessibility
    await validate_category_ownership(db, user_id, data.category_id)

    request_hash = None
    if idempotency_key:
        idempotency_key = idempotency_key.strip()
        request_hash = compute_payload_hash(user_id, data)

        # Check for existing idempotency record
        idem_stmt = select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.key == idempotency_key,
        )
        idem_result = await db.execute(idem_stmt)
        existing_record = idem_result.scalar_one_or_none()

        if existing_record:
            if existing_record.request_hash == request_hash:
                logger.info(
                    f"Idempotent hit for user {user_id} and key {idempotency_key}."
                )
                # Fetch and return the already created expense
                if existing_record.resource_id:
                    exp_stmt = select(Expense).where(
                        Expense.id == existing_record.resource_id,
                        Expense.user_id == user_id,
                    )
                    exp_res = await db.execute(exp_stmt)
                    cached_expense = exp_res.scalar_one_or_none()
                    if cached_expense:
                        return cached_expense, True

                # If expense was deleted or missing, return from response_body
                try:
                    cached_data = json.loads(existing_record.response_body)
                    parsed_resp = ExpenseResponse.model_validate(cached_data)
                    mock_expense = Expense(
                        id=parsed_resp.id,
                        user_id=parsed_resp.user_id,
                        category_id=parsed_resp.category_id,
                        amount_minor=parsed_resp.amount_minor,
                        description=parsed_resp.description,
                        expense_date=parsed_resp.expense_date,
                        notes=parsed_resp.notes,
                        merchant=parsed_resp.merchant,
                        payment_mode=parsed_resp.payment_mode,
                        receipt_id=parsed_resp.receipt_id,
                        version=parsed_resp.version,
                        created_at=parsed_resp.created_at,
                        updated_at=parsed_resp.updated_at,
                        deleted_at=parsed_resp.deleted_at,
                    )
                    return mock_expense, True
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning(f"Failed to parse stored idempotency body: {exc}")
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "Idempotency key has already been used with a different request payload.",
                    },
                )

    # 2. Instantiate new Expense model
    now = utcnow()
    expense = Expense(
        id=uuid.uuid4(),
        user_id=user_id,
        category_id=data.category_id,
        amount_minor=data.amount_minor,
        description=data.description,
        expense_date=data.expense_date or now.date(),
        notes=data.notes,
        merchant=data.merchant,
        payment_mode=data.payment_mode,
        receipt_id=data.receipt_id,
        version=1,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )

    db.add(expense)

    if idempotency_key and request_hash:
        # Serialise expected response for idempotency storage
        resp_schema = ExpenseResponse.model_validate(expense)
        idem_record = IdempotencyRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            key=idempotency_key,
            request_hash=request_hash,
            response_code=status.HTTP_201_CREATED,
            response_body=json.dumps(resp_schema.model_dump(mode="json")),
            resource_id=expense.id,
            created_at=now,
        )
        db.add(idem_record)

    try:
        await db.commit()
        await db.refresh(expense)
        return expense, False
    except IntegrityError as exc:
        await db.rollback()
        # Handle concurrent creation race with identical idempotency key
        if idempotency_key:
            idem_stmt = select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.key == idempotency_key,
            )
            idem_result = await db.execute(idem_stmt)
            existing_record = idem_result.scalar_one_or_none()
            if existing_record:
                if existing_record.request_hash == request_hash:
                    if existing_record.resource_id:
                        exp_stmt = select(Expense).where(
                            Expense.id == existing_record.resource_id,
                            Expense.user_id == user_id,
                        )
                        exp_res = await db.execute(exp_stmt)
                        cached_expense = exp_res.scalar_one_or_none()
                        if cached_expense:
                            return cached_expense, True
                else:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "IDEMPOTENCY_CONFLICT",
                            "message": "Idempotency key has already been used with a different request payload.",
                        },
                    ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INTEGRITY_ERROR",
                "message": "Could not create expense due to database constraint violation.",
            },
        ) from exc


async def get_expense(
    db: AsyncSession,
    user_id: uuid.UUID,
    expense_id: uuid.UUID,
    include_deleted: bool = False,
) -> Expense:
    """
    Retrieve an expense owned by the authenticated user.
    Raises HTTP 404 if the record does not exist, belongs to another user,
    or has been soft deleted (unless include_deleted=True).
    """
    stmt = select(Expense).where(
        Expense.id == expense_id,
        Expense.user_id == user_id,
    )
    if not include_deleted:
        stmt = stmt.where(Expense.deleted_at.is_(None))

    result = await db.execute(stmt)
    expense = result.scalar_one_or_none()

    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_FOUND",
                "message": "Expense not found.",
            },
        )

    return expense


async def list_expenses(
    db: AsyncSession,
    user_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Expense], int]:
    """
    List personal expenses for the authenticated user, excluding soft-deleted items.
    Supports filtering by category, date range, search query, and pagination.
    Returns:
      (expenses: List[Expense], total_count: int)
    """
    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]

    if category_id:
        base_where.append(Expense.category_id == category_id)
    if from_date:
        base_where.append(Expense.expense_date >= from_date)
    if to_date:
        base_where.append(Expense.expense_date <= to_date)
    if query:
        q_clean = query.strip()
        if q_clean:
            base_where.append(
                (Expense.description.ilike(f"%{q_clean}%"))
                | (Expense.merchant.ilike(f"%{q_clean}%"))
            )

    # 1. Total count
    count_stmt = select(func.count(Expense.id)).where(*base_where)
    count_res = await db.execute(count_stmt)
    total_count = count_res.scalar_one() or 0

    # 2. Query page items
    stmt = (
        select(Expense)
        .where(*base_where)
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 100))
    )
    result = await db.execute(stmt)
    expenses = list(result.scalars().all())

    return expenses, total_count


async def update_expense(
    db: AsyncSession,
    user_id: uuid.UUID,
    expense_id: uuid.UUID,
    data: ExpenseUpdate,
    expected_version: int | None = None,
) -> Expense:
    """
    Update an existing expense with optimistic concurrency control.
    Requirements:
      - Expense must belong to authenticated user and not be deleted (HTTP 404 otherwise).
      - Expected version must be provided and must match current version (HTTP 409 otherwise).
      - Atomic update increments version and prevents concurrent lost updates.
    """
    # 1. Fetch current record
    current_expense = await get_expense(db, user_id, expense_id, include_deleted=False)

    # Determine expected version (from argument or data payload)
    version_to_check = expected_version if expected_version is not None else data.version
    if version_to_check is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_REQUIRED",
                "message": "Update requires 'version' in body or 'If-Match' header for optimistic concurrency.",
            },
        )

    if current_expense.version != version_to_check:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "message": f"Version conflict. Expected version {version_to_check}, but record is currently version {current_expense.version}.",
            },
        )

    # 2. Validate category if updated
    if data.category_id is not None and data.category_id != current_expense.category_id:
        await validate_category_ownership(db, user_id, data.category_id)

    # 3. Build update dictionary
    updates: dict[str, Any] = {}
    if data.amount_minor is not None:
        updates["amount_minor"] = data.amount_minor
    if data.description is not None:
        updates["description"] = data.description
    if data.category_id is not None:
        updates["category_id"] = data.category_id
    if data.expense_date is not None:
        updates["expense_date"] = data.expense_date
    if data.notes is not None:
        updates["notes"] = data.notes
    if data.merchant is not None:
        updates["merchant"] = data.merchant
    if data.payment_mode is not None:
        updates["payment_mode"] = data.payment_mode
    if data.receipt_id is not None:
        updates["receipt_id"] = data.receipt_id

    now = utcnow()
    updates["updated_at"] = now
    new_version = current_expense.version + 1

    # 4. Atomic conditional update statement
    stmt = (
        update(Expense)
        .where(
            Expense.id == expense_id,
            Expense.user_id == user_id,
            Expense.version == version_to_check,
            Expense.deleted_at.is_(None),
        )
        .values(**updates, version=new_version)
    )
    result = await db.execute(stmt)

    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "message": "Concurrent update detected. The record was modified by another request.",
            },
        )

    await db.commit()

    # Re-fetch the updated expense
    return await get_expense(db, user_id, expense_id, include_deleted=False)


async def soft_delete_expense(
    db: AsyncSession,
    user_id: uuid.UUID,
    expense_id: uuid.UUID,
) -> Expense:
    """
    Soft-delete an expense by setting deleted_at to current UTC time.
    Preserves the record and its audit history.
    Raises HTTP 404 if not found or already deleted.
    """
    expense = await get_expense(db, user_id, expense_id, include_deleted=False)

    now = utcnow()
    expense.deleted_at = now
    expense.version += 1
    expense.updated_at = now

    await db.commit()
    await db.refresh(expense)
    logger.info(f"Soft-deleted expense {expense_id} for user {user_id}.")
    return expense


async def restore_expense(
    db: AsyncSession,
    user_id: uuid.UUID,
    expense_id: uuid.UUID,
) -> Expense:
    """
    Restore a soft-deleted expense, making it visible in queries and totals again.
    Raises HTTP 404 if the record does not exist or belongs to another user.
    Raises HTTP 400 if the expense is not currently soft-deleted.
    """
    # Fetch record including deleted
    expense = await get_expense(db, user_id, expense_id, include_deleted=True)

    if expense.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EXPENSE_NOT_DELETED",
                "message": "Expense is not deleted and cannot be restored.",
            },
        )

    now = utcnow()
    expense.deleted_at = None
    expense.version += 1
    expense.updated_at = now

    await db.commit()
    await db.refresh(expense)
    logger.info(f"Restored expense {expense_id} for user {user_id}.")
    return expense


async def get_user_expense_total(
    db: AsyncSession,
    user_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[int, int]:
    """
    Calculate total spending in integer paise for the authenticated user.
    Strictly excludes soft-deleted records.
    Returns:
      (total_paise: int, count: int)
    """
    base_where = [
        Expense.user_id == user_id,
        Expense.deleted_at.is_(None),
    ]
    if from_date:
        base_where.append(Expense.expense_date >= from_date)
    if to_date:
        base_where.append(Expense.expense_date <= to_date)

    stmt = select(
        func.coalesce(func.sum(Expense.amount_minor), 0),
        func.count(Expense.id),
    ).where(*base_where)

    result = await db.execute(stmt)
    total_paise, count = result.one()
    return int(total_paise), int(count)
