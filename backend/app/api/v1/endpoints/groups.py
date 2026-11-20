import re
import uuid
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.rate_limit_deps import limit_by_user
from app.core.rate_limiter import RATE_LIMIT_RESPONSES
from app.core.database import get_db
from app.models.user import User
from app.schemas.group import (
    CreateInvitationRequest,
    GroupCreateRequest,
    GroupListItemResponse,
    GroupResponse,
    InvitationResponse,
    JoinCodeResponse,
    JoinGroupRequest,
    JoinGroupResponse,
)
from app.schemas.settlement import (
    GroupBalancesResponse,
    SettlementCreateRequest,
    SettlementResponse,
    SimplifiedRepaymentsResponse,
)
from app.schemas.shared_expense import (
    GroupHistoryItemResponse,
    SharedExpenseCreateRequest,
    SharedExpenseDeleteResponse,
    SharedExpenseResponse,
    SharedExpenseUpdateRequest,
)
from app.services import group_service, settlement_service, shared_expense_service

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
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new group",
    description="Supports idempotent retries via the Idempotency-Key header. A replayed response "
    "does not repeat the join code (codes are stored only as hashes); generate a new one if needed.",
)
async def create_group(
    payload: GroupCreateRequest,
    response: Response,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new group with the specified group type.
    The creator is assigned as admin, and an initial 7-day join code is generated and returned securely.
    """
    result, is_replay = await group_service.create_group(
        db, current_user, payload, idempotency_key=idempotency_key
    )
    if is_replay:
        response.headers["X-Idempotent-Replay"] = "true"
    return result


@router.get(
    "",
    response_model=List[GroupListItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List current user's groups",
)
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active groups that the authenticated user is a member of."""
    return await group_service.list_user_groups(db, current_user)


@router.post(
    "/join",
    response_model=JoinGroupResponse,
    dependencies=[Depends(limit_by_user("join_user"))],
    responses=RATE_LIMIT_RESPONSES,
    status_code=status.HTTP_200_OK,
    summary="Join group with code",
)
async def join_group(
    payload: JoinGroupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Join a group using a valid, unexpired, and unrevoked join code.
    Prevents duplicate active memberships.
    """
    group_dto = await group_service.join_group_by_code(db, current_user, payload.code)
    return JoinGroupResponse(
        message="Successfully joined the group.",
        group=group_dto,
    )


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Get group details",
)
async def get_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch group details and member list. Restricted to group members and admins."""
    return await group_service.get_group_details(db, group_id, current_user)


@router.post(
    "/{group_id}/join-code",
    response_model=JoinCodeResponse,
    dependencies=[Depends(limit_by_user("join_code_user"))],
    responses=RATE_LIMIT_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    summary="Generate or rotate join code",
)
async def generate_join_code(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Owner/admin generates a new cryptographically secure 8-character join code.
    Revokes any previously active join codes for this group.
    """
    return await group_service.generate_join_code(db, group_id, current_user)


@router.delete(
    "/{group_id}/join-code",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke join code",
)
async def revoke_join_code(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner/admin revokes the active join code for this group."""
    await group_service.revoke_join_code(db, group_id, current_user)


@router.post(
    "/{group_id}/invitations",
    response_model=InvitationResponse,
    dependencies=[Depends(limit_by_user("invite_user"))],
    responses=RATE_LIMIT_RESPONSES,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a member",
)
async def invite_member(
    group_id: uuid.UUID,
    payload: CreateInvitationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner/admin creates an in-app invitation for a user by email, phone, or user_id."""
    return await group_service.create_invitation(db, group_id, payload, current_user)


@router.get(
    "/{group_id}/invitations",
    response_model=List[InvitationResponse],
    status_code=status.HTTP_200_OK,
    summary="List group invitations",
)
async def list_group_invitations(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner/admin lists all invitations issued for this group."""
    return await group_service.list_group_invitations(db, group_id, current_user)


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a group member, or leave the group",
)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Owner/admin removes a member from the group (status 'removed').
    Any active member may pass their own user ID to leave (status 'left').
    The group owner can be neither removed nor leave.
    Both are soft changes, so financial history is preserved.
    """
    await group_service.remove_member(db, group_id, user_id, current_user)


@router.post(
    "/{group_id}/expenses",
    response_model=SharedExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a shared expense to group",
    description="Supports idempotent retries via the Idempotency-Key header.",
)
async def create_shared_expense(
    group_id: uuid.UUID,
    payload: SharedExpenseCreateRequest,
    response: Response,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a shared expense within the specified group.
    Supports equal, exact, percentage, and parts-based split modes using the pure ledger engine.
    Ensures all payments, shares, and audit logs are recorded in one atomic transaction.
    """
    result, is_replay = await shared_expense_service.create_shared_expense(
        db, group_id, current_user, payload, idempotency_key=idempotency_key
    )
    if is_replay:
        response.headers["X-Idempotent-Replay"] = "true"
    return result


@router.get(
    "/{group_id}/expenses",
    response_model=List[SharedExpenseResponse],
    status_code=status.HTTP_200_OK,
    summary="List shared expenses of group",
)
async def list_shared_expenses(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all shared expenses for this group, ordered from newest to oldest."""
    return await shared_expense_service.list_shared_expenses(db, group_id, current_user)


@router.get(
    "/{group_id}/balances",
    response_model=GroupBalancesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get group balances and suggested settlements",
)
async def get_group_balances(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Net position per member (expenses and settlements) and simplified transfers,
    computed only by the pure ledger engine. Non-members get 404.
    """
    return await settlement_service.get_group_balances(db, group_id, current_user)


@router.get(
    "/{group_id}/balances/simplified",
    response_model=SimplifiedRepaymentsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get simplified repayment suggestions",
)
async def get_simplified_repayments(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Greedy 'who pays whom' suggestions from ledger.simplify(). Non-members get 404."""
    return await settlement_service.get_simplified_repayments(db, group_id, current_user)


@router.post(
    "/{group_id}/settlements",
    response_model=SettlementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a full or partial settlement",
    description="Records that one member repaid another. Never counted as spending or income. "
    "Supports idempotent retries via the Idempotency-Key header.",
)
async def create_settlement(
    group_id: uuid.UUID,
    payload: SettlementCreateRequest,
    response: Response,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Payer and payee must be different active members; the amount cannot exceed what the
    payer owes the payee. The settlement and its audit event are written in one transaction.
    """
    result, is_replay = await settlement_service.create_settlement(
        db, group_id, current_user, payload, idempotency_key=idempotency_key
    )
    if is_replay:
        response.headers["X-Idempotent-Replay"] = "true"
    return result


@router.get(
    "/{group_id}/settlements",
    response_model=List[SettlementResponse],
    status_code=status.HTTP_200_OK,
    summary="List settlements of group",
)
async def list_settlements(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all settlements recorded in this group, newest first. Non-members get 404."""
    return await settlement_service.list_settlements(db, group_id, current_user)


@router.get(
    "/{group_id}/expenses/{expense_id}",
    response_model=SharedExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get shared expense details",
)
async def get_shared_expense(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch details of a single shared expense including payments, shares, and current version."""
    return await shared_expense_service.get_shared_expense(
        db, group_id, expense_id, current_user
    )


@router.patch(
    "/{group_id}/expenses/{expense_id}",
    response_model=SharedExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a shared expense",
)
async def update_shared_expense(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: SharedExpenseUpdateRequest,
    if_match: Annotated[Optional[str], Header(alias="If-Match")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing shared expense with optimistic concurrency and balance recalculation.
    Only the original expense creator or a group admin can edit.
    Recalculates group member balances and stores before-and-after audit logs atomically.
    Sends notifications to all active members only after commit.
    """
    header_version = parse_if_match_header(if_match)
    expected_version = header_version if header_version is not None else payload.version
    return await shared_expense_service.update_shared_expense(
        db=db,
        group_id=group_id,
        expense_id=expense_id,
        current_user=current_user,
        payload=payload,
        expected_version=expected_version,
    )


@router.put(
    "/{group_id}/expenses/{expense_id}",
    response_model=SharedExpenseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a shared expense (full)",
)
async def update_shared_expense_put(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    payload: SharedExpenseUpdateRequest,
    if_match: Annotated[Optional[str], Header(alias="If-Match")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full update alias for shared expense."""
    header_version = parse_if_match_header(if_match)
    expected_version = header_version if header_version is not None else payload.version
    return await shared_expense_service.update_shared_expense(
        db=db,
        group_id=group_id,
        expense_id=expense_id,
        current_user=current_user,
        payload=payload,
        expected_version=expected_version,
    )


@router.delete(
    "/{group_id}/expenses/{expense_id}",
    response_model=SharedExpenseDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a shared expense",
)
async def delete_shared_expense(
    group_id: uuid.UUID,
    expense_id: uuid.UUID,
    version: Annotated[Optional[int], Query(description="Expected version for optimistic concurrency")] = None,
    if_match: Annotated[Optional[str], Header(alias="If-Match")] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-delete a shared expense with optimistic concurrency and balance recalculation.
    Only the original expense creator or a group admin can delete.
    Preserves audit history and dispatches notifications to group members only after commit.
    """
    header_version = parse_if_match_header(if_match)
    expected_version = header_version if header_version is not None else version
    result = await shared_expense_service.delete_shared_expense(
        db=db,
        group_id=group_id,
        expense_id=expense_id,
        current_user=current_user,
        expected_version=expected_version,
    )
    return SharedExpenseDeleteResponse(**result)


@router.get(
    "/{group_id}/history",
    response_model=List[GroupHistoryItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Get group transaction and audit history",
)
async def get_group_history(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve full audit log and transaction history for this group."""
    items = await shared_expense_service.get_group_history(db, group_id, current_user)
    return [GroupHistoryItemResponse(**item) for item in items]



