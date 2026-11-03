import re
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.authorization import (
    ALLOWED_EXPENSE_UPDATE_FIELDS,
    validate_protected_fields_update,
)
from app.core.database import get_db
from app.models.user import User
from app.schemas.expense import (
    ExpenseCreate,
    ExpenseDataResponse,
    ExpenseDeleteResponse,
    ExpenseListMeta,
    ExpenseListResponse,
    ExpenseResponse,
    ExpenseRestoreResponse,
    ExpenseTotalData,
    ExpenseTotalResponse,
    ExpenseUpdate,
)
from app.services import expenses as expense_service

router = APIRouter()


def parse_if_match_header(if_match: str | None) -> int | None:
    """Parse integer version from HTTP If-Match header (e.g. '1', '"1"', 'W/"1"')."""
    if not if_match:
        return None
    match = re.search(r"\d+", if_match)
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    return None


@router.post(
    "",
    response_model=ExpenseDataResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a personal expense",
    description="Creates a new personal expense record for the authenticated user. "
    "Supports idempotent retries via the Idempotency-Key header.",
)
async def create_expense_endpoint(
    data: ExpenseCreate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExpenseDataResponse:
    # Reject client-supplied ownership tampering in request body
    try:
        raw_body = await request.json()
    except Exception:
        raw_body = None

    if isinstance(raw_body, dict):
        client_user_id = raw_body.get("user_id") or raw_body.get("userId")
        if client_user_id is not None and str(client_user_id).strip() != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PROTECTED_FIELD_MODIFICATION",
                    "message": "Cannot specify or modify record ownership (user_id). Record is bound to authenticated user.",
                },
            )

    expense, is_cached = await expense_service.create_expense(
        db=db,
        user_id=current_user.id,
        data=data,
        idempotency_key=idempotency_key,
    )
    if is_cached:
        # Idempotent response
        response.headers["X-Idempotent-Replay"] = "true"

    return ExpenseDataResponse(data=ExpenseResponse.model_validate(expense))


@router.get(
    "",
    response_model=ExpenseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List personal expenses",
    description="Returns a paginated list of personal expenses owned by the authenticated user. "
    "Soft-deleted records are automatically excluded.",
)
async def list_expenses_endpoint(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category_id: Annotated[uuid.UUID | None, Query(description="Filter by category UUID")] = None,
    from_date: Annotated[date | None, Query(alias="from", description="Filter expenses on or after this date")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="Filter expenses on or before this date")] = None,
    query: Annotated[str | None, Query(alias="q", description="Search text in description or merchant")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page limit (1-100)")] = 50,
    offset: Annotated[int, Query(ge=0, description="Page offset")] = 0,
) -> ExpenseListResponse:
    # Disallow foreign user_id query parameter tampering
    foreign_user = request.query_params.get("user_id") or request.query_params.get("userId")
    if foreign_user and foreign_user.strip() != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Accessing another user's expenses via query parameters is not permitted.",
            },
        )

    expenses, total = await expense_service.list_expenses(
        db=db,
        user_id=current_user.id,
        category_id=category_id,
        from_date=from_date,
        to_date=to_date,
        query=query,
        limit=limit,
        offset=offset,
    )
    items = [ExpenseResponse.model_validate(exp) for exp in expenses]
    meta = ExpenseListMeta(
        total=total,
        limit=limit,
        offset=offset,
        next_cursor=str(offset + limit) if (offset + limit) < total else None,
    )
    return ExpenseListResponse(data=items, meta=meta)


@router.get(
    "/totals",
    response_model=ExpenseTotalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get personal expense spending totals",
    description="Calculates the total spending amount in integer paise for active personal expenses. "
    "Soft-deleted expenses are strictly excluded.",
)
async def get_expense_totals_endpoint(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from", description="Start date for totals")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="End date for totals")] = None,
) -> ExpenseTotalResponse:
    # Disallow foreign user_id query parameter tampering
    foreign_user = request.query_params.get("user_id") or request.query_params.get("userId")
    if foreign_user and foreign_user.strip() != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": "Accessing another user's expense totals via query parameters is not permitted.",
            },
        )

    total_paise, count = await expense_service.get_user_expense_total(
        db=db,
        user_id=current_user.id,
        from_date=from_date,
        to_date=to_date,
    )
    return ExpenseTotalResponse(
        data=ExpenseTotalData(
            total_paise=total_paise,
            currency="INR",
            count=count,
        )
    )


@router.get(
    "/{expense_id}",
    response_model=ExpenseDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve an expense by ID",
    description="Retrieves a single personal expense owned by the authenticated user. "
    "Accessing another user's expense or a deleted expense returns 404.",
)
async def get_expense_endpoint(
    expense_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExpenseDataResponse:
    expense = await expense_service.get_expense(
        db=db,
        user_id=current_user.id,
        expense_id=expense_id,
        include_deleted=False,
    )
    return ExpenseDataResponse(data=ExpenseResponse.model_validate(expense))


@router.patch(
    "/{expense_id}",
    response_model=ExpenseDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an existing expense",
    description="Updates fields of an existing personal expense with optimistic concurrency. "
    "The client must supply the known version in the request body or via the If-Match header. "
    "Returns 409 Conflict if the version is stale.",
)
async def update_expense_endpoint(
    expense_id: uuid.UUID,
    data: ExpenseUpdate,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ExpenseDataResponse:
    # 1. Enforce rejection of protected/disallowed fields in update payload
    try:
        raw_body = await request.json()
    except Exception:
        raw_body = None

    if isinstance(raw_body, dict):
        validate_protected_fields_update(raw_body, allowed_fields=ALLOWED_EXPENSE_UPDATE_FIELDS)

    header_version = parse_if_match_header(if_match)
    expected_version = header_version if header_version is not None else data.version

    updated_expense = await expense_service.update_expense(
        db=db,
        user_id=current_user.id,
        expense_id=expense_id,
        data=data,
        expected_version=expected_version,
    )
    return ExpenseDataResponse(data=ExpenseResponse.model_validate(updated_expense))


@router.delete(
    "/{expense_id}",
    response_model=ExpenseDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft delete an expense",
    description="Marks a personal expense as soft-deleted. The record remains stored in the database "
    "for auditability, but is excluded from ordinary queries and spending totals.",
)
async def delete_expense_endpoint(
    expense_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExpenseDeleteResponse:
    deleted_expense = await expense_service.soft_delete_expense(
        db=db,
        user_id=current_user.id,
        expense_id=expense_id,
    )
    return ExpenseDeleteResponse(
        data={
            "id": str(deleted_expense.id),
            "deleted": True,
            "version": deleted_expense.version,
        },
        message="Expense deleted successfully.",
    )


@router.post(
    "/{expense_id}/restore",
    response_model=ExpenseRestoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Restore a soft-deleted expense",
    description="Restores a previously soft-deleted personal expense, making it visible again "
    "in ordinary listings and spending totals.",
)
async def restore_expense_endpoint(
    expense_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExpenseRestoreResponse:
    restored_expense = await expense_service.restore_expense(
        db=db,
        user_id=current_user.id,
        expense_id=expense_id,
    )
    return ExpenseRestoreResponse(
        data=ExpenseResponse.model_validate(restored_expense),
        message="Expense restored successfully.",
    )
