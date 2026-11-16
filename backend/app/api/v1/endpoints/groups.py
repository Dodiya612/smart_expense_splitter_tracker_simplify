import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
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
from app.schemas.shared_expense import (
    SharedExpenseCreateRequest,
    SharedExpenseResponse,
)
from app.services import group_service, shared_expense_service

router = APIRouter()


@router.post(
    "",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new group",
)
async def create_group(
    payload: GroupCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new group with the specified group type.
    The creator is assigned as admin, and an initial 7-day join code is generated and returned securely.
    """
    group, raw_join_code = await group_service.create_group(db, current_user, payload)
    return group_service.format_group_response(group, current_user.id, join_code=raw_join_code)


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
    summary="Remove a group member",
)
async def remove_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Owner/admin removes a member from the group.
    The group owner cannot be removed.
    Removal is soft, setting status to 'removed' to preserve financial history.
    """
    await group_service.remove_member(db, group_id, user_id, current_user)


@router.post(
    "/{group_id}/expenses",
    response_model=SharedExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a shared expense to group",
)
async def create_shared_expense(
    group_id: uuid.UUID,
    payload: SharedExpenseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a shared expense within the specified group.
    Supports equal, exact, percentage, and parts-based split modes using the pure ledger engine.
    Ensures all payments, shares, and audit logs are recorded in one atomic transaction.
    """
    return await shared_expense_service.create_shared_expense(db, group_id, current_user, payload)


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
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get group balances and suggested settlements",
)
async def get_group_balances(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate dynamic net member balances and suggested minimal settlement transfers
    using the pure ledger engine.
    """
    return await shared_expense_service.get_group_balances(db, group_id, current_user)


