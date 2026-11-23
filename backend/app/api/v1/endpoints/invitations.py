import uuid
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.rate_limit_deps import limit_by_user
from app.core.rate_limiter import RATE_LIMIT_RESPONSES
from app.core.database import get_db
from app.models.user import User
from app.schemas.group import InvitationResponse, JoinGroupResponse
from app.services import group_service

router = APIRouter()


@router.get(
    "",
    response_model=List[InvitationResponse],
    status_code=status.HTTP_200_OK,
    summary="List pending invitations for current user",
)
async def list_my_invitations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List pending in-app invitations addressed to the current authenticated user."""
    return await group_service.list_user_pending_invitations(db, current_user)


@router.post(
    "/{invitation_id}/accept",
    dependencies=[Depends(limit_by_user("invite_respond_user"))],
    responses=RATE_LIMIT_RESPONSES,
    response_model=JoinGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept an invitation",
)
async def accept_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept an in-app invitation and join the group as an active member.
    The invitation must belong to the authenticated user and be in pending status.
    """
    group_dto = await group_service.accept_invitation(db, invitation_id, current_user)
    return JoinGroupResponse(
        message="Invitation accepted successfully.",
        group=group_dto,
    )


@router.post(
    "/{invitation_id}/decline",
    dependencies=[Depends(limit_by_user("invite_respond_user"))],
    responses=RATE_LIMIT_RESPONSES,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline an invitation",
)
async def decline_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Decline an in-app invitation.
    The invitation status transitions to declined.
    """
    await group_service.decline_invitation(db, invitation_id, current_user)

