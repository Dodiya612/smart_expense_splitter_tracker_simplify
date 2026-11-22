import hashlib
import logging
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.authorization import GroupPolicy
from app.models.group import (
    Group,
    GroupInvitation,
    GroupMember,
    GroupMemberRole,
    GroupMemberStatus,
    InvitationStatus,
)
from app.models.user import User
from app.services.notifications import current_member_roles, notify_group_members, notify_users
from app.schemas.group import (
    CreateInvitationRequest,
    GroupCreateRequest,
    GroupListItemResponse,
    GroupMemberResponse,
    GroupResponse,
    GroupUpdateRequest,
    InvitationResponse,
    JoinCodeResponse,
)
from app.services import idempotency


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_secure_code(length: int = 8) -> str:
    """
    Generate an 8-character cryptographically secure, unpredictable code.
    Excludes ambiguous characters (0, O, 1, I) to prevent user transcription errors.
    """
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_code(raw_code: str) -> str:
    """Return SHA-256 hash of normalized code."""
    normalized = raw_code.strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def get_group_or_404(db: AsyncSession, group_id: uuid.UUID) -> Group:
    """Load group by ID or raise 404."""
    result = await db.execute(
        select(Group)
        .options(
            selectinload(Group.members).selectinload(GroupMember.user),
            selectinload(Group.creator),
        )
        .where(Group.id == group_id, Group.archived_at.is_(None))
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GROUP_NOT_FOUND", "message": "Group not found."},
        )
    return group


def check_group_membership(
    group: Group,
    user: User,
    require_admin: bool = False,
) -> GroupMember:
    """
    Enforces authorization using GroupPolicy.
    Raises 403 GROUP_ACCESS_DENIED or INSUFFICIENT_PERMISSIONS.
    """
    active_members = {
        m.user_id: m for m in group.members if m.status == GroupMemberStatus.ACTIVE.value
    }
    member_ids = set(active_members.keys())
    admin_ids = {
        m.user_id
        for m in group.members
        if m.status == GroupMemberStatus.ACTIVE.value
        and m.role == GroupMemberRole.ADMIN.value
    }

    if require_admin:
        GroupPolicy.authorize_admin(user, group.id, member_ids, admin_ids)
    else:
        GroupPolicy.authorize_member(user, group.id, member_ids)

    return active_members[user.id]


def format_group_response(
    group: Group,
    current_user_id: uuid.UUID,
    join_code: Optional[str] = None,
) -> GroupResponse:
    """Build response DTO including members and current user's role."""
    member_dtos: List[GroupMemberResponse] = []
    user_role: Optional[str] = None

    for m in group.members:
        if m.status == GroupMemberStatus.ACTIVE.value:
            user_name = m.user.name if m.user else "Unknown"
            user_email = m.user.email if m.user else ""
            member_dtos.append(
                GroupMemberResponse(
                    user_id=m.user_id,
                    name=user_name,
                    email=user_email,
                    role=m.role,
                    status=m.status,
                    joined_at=m.joined_at,
                )
            )
            if m.user_id == current_user_id:
                user_role = m.role

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        type=group.type,
        created_by=group.created_by,
        archived_at=group.archived_at,
        created_at=group.created_at,
        updated_at=group.updated_at,
        members=member_dtos,
        current_user_role=user_role,
        join_code=join_code,
    )


async def create_group(
    db: AsyncSession,
    user: User,
    payload: GroupCreateRequest,
    idempotency_key: Optional[str] = None,
) -> Tuple[GroupResponse, bool]:
    """
    Creates a new group, makes the user owner/admin, and creates an initial join code.
    Returns (response with the single-use plaintext join code, is_replay).

    With an Idempotency-Key (US-34): a retry with the same body replays the original
    response (is_replay=True); the same key with a different body is 409. The stored
    replay never contains the plaintext join code, because join codes are kept only
    as hashes; a replay therefore returns join_code=None.
    """
    idempotency_key, hashed_request, replay = await idempotency.prepare(
        db, user.id, idempotency_key, "group_create", None, payload, GroupResponse
    )
    if replay is not None:
        return replay, True

    now = utcnow()
    group = Group(
        name=payload.name,
        description=payload.description,
        type=payload.type.value,
        created_by=user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(group)
    await db.flush()

    # Add creator as admin member
    member = GroupMember(
        group_id=group.id,
        user_id=user.id,
        role=GroupMemberRole.ADMIN.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now,
        updated_at=now,
    )
    db.add(member)

    # Generate initial 7-day join code
    raw_code = generate_secure_code(8)
    code_hash = hash_code(raw_code)
    invitation = GroupInvitation(
        group_id=group.id,
        code_hash=code_hash,
        status=InvitationStatus.PENDING.value,
        created_by=user.id,
        expires_at=now + timedelta(days=7),
        created_at=now,
    )
    db.add(invitation)

    if idempotency_key and hashed_request:
        # Built from the in-memory rows (no lazy loads before commit); no join code.
        stored_response = GroupResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            type=group.type,
            created_by=group.created_by,
            archived_at=None,
            created_at=group.created_at,
            updated_at=group.updated_at,
            members=[
                GroupMemberResponse(
                    user_id=user.id,
                    name=user.name,
                    email=user.email,
                    role=member.role,
                    status=member.status,
                    joined_at=member.joined_at,
                )
            ],
            current_user_role=member.role,
            join_code=None,
        )
        idempotency.stage_record(
            db, user.id, idempotency_key, hashed_request, stored_response, group.id
        )

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Concurrent retry with the same key: return the winner's response.
        replay = await idempotency.replay_after_conflict(
            db, user.id, idempotency_key, hashed_request, GroupResponse
        )
        if replay is None:
            raise
        return replay, True
    # Refresh group with relationships loaded
    group = await get_group_or_404(db, group.id)
    return format_group_response(group, user.id, join_code=raw_code), False


async def list_user_groups(
    db: AsyncSession,
    current_user: User,
) -> List[GroupListItemResponse]:
    """List groups that the user is an active member of."""
    result = await db.execute(
        select(Group, GroupMember.role)
        .join(GroupMember, Group.id == GroupMember.group_id)
        .where(
            GroupMember.user_id == current_user.id,
            GroupMember.status == GroupMemberStatus.ACTIVE.value,
            Group.archived_at.is_(None),
        )
        .order_by(Group.created_at.desc())
    )
    rows = result.all()

    items: List[GroupListItemResponse] = []
    for grp, role in rows:
        # Count active members
        cnt_res = await db.execute(
            select(func.count())
            .select_from(GroupMember)
            .where(
                GroupMember.group_id == grp.id,
                GroupMember.status == GroupMemberStatus.ACTIVE.value,
            )
        )
        member_count = cnt_res.scalar() or 0
        items.append(
            GroupListItemResponse(
                id=grp.id,
                name=grp.name,
                description=grp.description,
                type=grp.type,
                created_by=grp.created_by,
                created_at=grp.created_at,
                member_count=member_count,
                current_user_role=role,
            )
        )
    return items


async def get_group_details(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> GroupResponse:
    """Fetch group details; enforces member/admin authorization."""
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=False)
    return format_group_response(group, current_user.id)


async def generate_join_code(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> JoinCodeResponse:
    """
    Owner/admin generates or rotates a join code.
    Revokes previous active join codes for this group.
    """
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=True)

    now = utcnow()
    # Revoke existing pending join codes
    result = await db.execute(
        select(GroupInvitation).where(
            GroupInvitation.group_id == group_id,
            GroupInvitation.code_hash.isnot(None),
            GroupInvitation.status == InvitationStatus.PENDING.value,
        )
    )
    existing_codes = result.scalars().all()
    for inv in existing_codes:
        inv.status = InvitationStatus.REVOKED.value

    # Create new join code
    raw_code = generate_secure_code(8)
    code_hash = hash_code(raw_code)
    expires_at = now + timedelta(days=7)

    new_invitation = GroupInvitation(
        group_id=group_id,
        code_hash=code_hash,
        status=InvitationStatus.PENDING.value,
        created_by=current_user.id,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(new_invitation)
    await db.commit()

    return JoinCodeResponse(
        group_id=group_id,
        code=raw_code,
        expires_at=expires_at,
    )


async def revoke_join_code(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> None:
    """Owner/admin revokes active join codes for this group."""
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=True)

    result = await db.execute(
        select(GroupInvitation).where(
            GroupInvitation.group_id == group_id,
            GroupInvitation.code_hash.isnot(None),
            GroupInvitation.status == InvitationStatus.PENDING.value,
        )
    )
    existing_codes = result.scalars().all()
    for inv in existing_codes:
        inv.status = InvitationStatus.REVOKED.value
    await db.commit()


logger = logging.getLogger(__name__)


def _group_payload(group: Group, actor: User) -> dict:
    return {
        "group_id": str(group.id),
        "group_name": group.name,
        "actor_name": actor.name,
    }


async def _notify_member_joined(
    db: AsyncSession,
    group: Group, joiner: User, joined_at: datetime, exclude: tuple | list = ()
) -> None:
    """Post-commit: active members (not the joiner) hear that someone joined.

    The joined_at time is in the key, so someone who leaves and rejoins notifies again.
    """
    try:
        await notify_group_members(
            group, joiner.id, "member_joined",
            f"{group.id}:{joiner.id}:{joined_at.isoformat()}",
            _group_payload(group, joiner),
            exclude=exclude,
            db=db,
        )
    except Exception:  # noqa: BLE001 - the join is already committed
        logger.exception("Join notification failed after commit; membership kept.")


async def _notify_member_removed(
    db: AsyncSession,
    group: Group, actor: User, member: GroupMember, is_leaving: bool
) -> None:
    """Post-commit: tell the removed user, and tell the active admins.

    ``group`` was loaded before the status change but the member row is the same
    object, so ``group.members`` already shows the new status; the removed user is
    never counted as an active recipient.
    """
    by_id = {m.user_id: m for m in group.members}
    target = by_id.get(member.user_id)
    target_name = target.user.name if target is not None and target.user is not None else "A member"
    ref = f"{group.id}:{member.user_id}:{member.updated_at.isoformat()}"
    payload = {**_group_payload(group, actor), "target_id": str(member.user_id), "target_name": target_name}
    roles = await current_member_roles(db, group)
    admins = [
        user_id for user_id, role in roles.items()
        if role == GroupMemberRole.ADMIN.value and user_id != member.user_id
    ]
    if is_leaving:
        await notify_users(admins, actor.id, "member_left", ref, payload, group_id=group.id)
        return
    await notify_users(
        [member.user_id], actor.id, "member_removed", ref,
        {**payload, "you": True}, group_id=group.id,
    )
    await notify_users(admins, actor.id, "member_removed", ref, payload, group_id=group.id)


async def join_group_by_code(
    db: AsyncSession,
    current_user: User,
    raw_code: str,
) -> GroupResponse:
    """
    User joins a group using a plaintext join code.
    Validates hash, expiry, revocation, and prevents duplicate memberships.
    """
    hashed = hash_code(raw_code)
    result = await db.execute(
        select(GroupInvitation).where(
            GroupInvitation.code_hash == hashed,
        )
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_JOIN_CODE", "message": "Invalid join code."},
        )

    if invitation.status == InvitationStatus.REVOKED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "JOIN_CODE_REVOKED", "message": "This join code has been revoked."},
        )

    now = utcnow()
    if invitation.expires_at <= now or invitation.status == InvitationStatus.EXPIRED.value:
        invitation.status = InvitationStatus.EXPIRED.value
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "JOIN_CODE_EXPIRED", "message": "This join code has expired."},
        )

    if invitation.status != InvitationStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_JOIN_CODE", "message": "Join code is no longer active."},
        )

    # Check target group exists and is active
    group = await get_group_or_404(db, invitation.group_id)

    # Check for existing membership
    mem_res = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == current_user.id,
        )
    )
    existing_member = mem_res.scalar_one_or_none()

    if existing_member:
        if existing_member.status == GroupMemberStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ALREADY_MEMBER", "message": "You are already a member of this group."},
            )
        # Reactivate membership if left or removed
        existing_member.status = GroupMemberStatus.ACTIVE.value
        existing_member.role = GroupMemberRole.MEMBER.value
        existing_member.joined_at = now
        existing_member.updated_at = now
    else:
        new_member = GroupMember(
            group_id=group.id,
            user_id=current_user.id,
            role=GroupMemberRole.MEMBER.value,
            status=GroupMemberStatus.ACTIVE.value,
            joined_at=now,
            updated_at=now,
        )
        db.add(new_member)

    await db.commit()
    # Reload group to return updated state
    updated_group = await get_group_or_404(db, group.id)
    await _notify_member_joined(db, updated_group, current_user, now)
    return format_group_response(updated_group, current_user.id)


async def remove_member(
    db: AsyncSession,
    group_id: uuid.UUID,
    target_user_id: uuid.UUID,
    current_user: User,
) -> None:
    """
    Removes a member from the group, or lets a member leave (US-17 AC5, US-22).

    - Owner/admin removing someone else: status becomes 'removed'.
    - A member removing themselves (leaving): any active member may do this;
      status becomes 'left'. A balance does not block leaving; the app warns first.
    - The group owner can be neither removed nor leave, so an admin always remains.

    Membership rows are never deleted, so past shares and history stay intact,
    and people who left can no longer be added to new expenses.
    """
    group = await get_group_or_404(db, group_id)
    is_leaving = target_user_id == current_user.id
    check_group_membership(group, current_user, require_admin=not is_leaving)

    if target_user_id == group.created_by:
        message = (
            "The group owner cannot leave the group."
            if is_leaving
            else "The group owner cannot be removed."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "CANNOT_REMOVE_OWNER", "message": message},
        )

    res = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == target_user_id,
        )
    )
    member = res.scalar_one_or_none()

    if not member or member.status != GroupMemberStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "MEMBER_NOT_FOUND", "message": "Member not found in this group."},
        )

    # Soft removal per CF-08 and CF-16: leaving -> 'left', removal -> 'removed'
    member.status = (
        GroupMemberStatus.LEFT.value if is_leaving else GroupMemberStatus.REMOVED.value
    )
    member.updated_at = utcnow()
    await db.commit()
    try:
        await _notify_member_removed(db, group, current_user, member, is_leaving)
    except Exception:  # noqa: BLE001 - the removal is already committed
        logger.exception("Membership notification failed after commit; change kept.")


async def create_invitation(
    db: AsyncSession,
    group_id: uuid.UUID,
    payload: CreateInvitationRequest,
    current_user: User,
) -> InvitationResponse:
    """
    Owner/admin creates an in-app invitation for a user by email, phone, or user_id.
    """
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=True)

    if not payload.email and not payload.phone and not payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VALIDATION_ERROR", "message": "Must provide email, phone, or user_id to invite."},
        )

    invited_user: Optional[User] = None
    if payload.user_id:
        user_res = await db.execute(select(User).where(User.id == payload.user_id))
        invited_user = user_res.scalar_one_or_none()
    elif payload.email:
        email_clean = payload.email.strip().lower()
        user_res = await db.execute(select(User).where(func.lower(User.email) == email_clean))
        invited_user = user_res.scalar_one_or_none()

    # Check if target user is already a member
    if invited_user:
        mem_res = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.user_id == invited_user.id,
                GroupMember.status == GroupMemberStatus.ACTIVE.value,
            )
        )
        if mem_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ALREADY_MEMBER", "message": "User is already an active member of this group."},
            )

        # Check for existing pending invitation
        inv_res = await db.execute(
            select(GroupInvitation).where(
                GroupInvitation.group_id == group_id,
                GroupInvitation.invited_user_id == invited_user.id,
                GroupInvitation.status == InvitationStatus.PENDING.value,
                GroupInvitation.expires_at > utcnow(),
            )
        )
        if inv_res.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "INVITATION_ALREADY_EXISTS", "message": "A pending invitation already exists for this user."},
            )

    now = utcnow()
    invitation = GroupInvitation(
        group_id=group_id,
        invited_user_id=invited_user.id if invited_user else None,
        invited_email=str(payload.email) if payload.email else None,
        invited_phone=payload.phone,
        status=InvitationStatus.PENDING.value,
        created_by=current_user.id,
        expires_at=now + timedelta(days=7),
        created_at=now,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    if invited_user is not None:
        await notify_users(
            [invited_user.id], current_user.id, "invitation_received",
            str(invitation.id),
            {**_group_payload(group, current_user), "invitation_id": str(invitation.id)},
            group_id=group.id,
        )

    return InvitationResponse(
        id=invitation.id,
        group_id=group.id,
        group_name=group.name,
        group_type=group.type,
        status=invitation.status,
        invited_user_id=invitation.invited_user_id,
        invited_email=invitation.invited_email,
        invited_phone=invitation.invited_phone,
        created_by=invitation.created_by,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


async def list_group_invitations(
    db: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> List[InvitationResponse]:
    """Admin lists all invitations for a group."""
    group = await get_group_or_404(db, group_id)
    check_group_membership(group, current_user, require_admin=True)

    result = await db.execute(
        select(GroupInvitation)
        .where(GroupInvitation.group_id == group_id)
        .order_by(GroupInvitation.created_at.desc())
    )
    invitations = result.scalars().all()

    return [
        InvitationResponse(
            id=inv.id,
            group_id=group.id,
            group_name=group.name,
            group_type=group.type,
            status=inv.status,
            invited_user_id=inv.invited_user_id,
            invited_email=inv.invited_email,
            invited_phone=inv.invited_phone,
            created_by=inv.created_by,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv in invitations
    ]


async def list_user_pending_invitations(
    db: AsyncSession,
    current_user: User,
) -> List[InvitationResponse]:
    """List in-app invitations addressed to the current user."""
    now = utcnow()
    user_email = current_user.email.strip().lower()
    result = await db.execute(
        select(GroupInvitation, Group.name, Group.type)
        .join(Group, GroupInvitation.group_id == Group.id)
        .where(
            or_(
                GroupInvitation.invited_user_id == current_user.id,
                func.lower(GroupInvitation.invited_email) == user_email,
            ),
            GroupInvitation.status == InvitationStatus.PENDING.value,
            GroupInvitation.expires_at > now,
            Group.archived_at.is_(None),
        )
        .order_by(GroupInvitation.created_at.desc())
    )
    rows = result.all()

    return [
        InvitationResponse(
            id=inv.id,
            group_id=inv.group_id,
            group_name=grp_name,
            group_type=grp_type,
            status=inv.status,
            invited_user_id=inv.invited_user_id,
            invited_email=inv.invited_email,
            invited_phone=inv.invited_phone,
            created_by=inv.created_by,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
        )
        for inv, grp_name, grp_type in rows
    ]


async def accept_invitation(
    db: AsyncSession,
    invitation_id: uuid.UUID,
    current_user: User,
) -> GroupResponse:
    """
    Invited user accepts the invitation and joins the group.
    """
    user_email = current_user.email.strip().lower()
    result = await db.execute(
        select(GroupInvitation).where(GroupInvitation.id == invitation_id)
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVITATION_NOT_FOUND", "message": "Invitation not found."},
        )

    # Verify recipient identity
    matches_user = invitation.invited_user_id == current_user.id
    matches_email = (
        invitation.invited_email and invitation.invited_email.strip().lower() == user_email
    )
    if not matches_user and not matches_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVITATION_NOT_FOUND", "message": "Invitation not found."},
        )

    now = utcnow()
    if invitation.status == InvitationStatus.REVOKED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVITATION_REVOKED", "message": "This invitation has been revoked."},
        )

    if invitation.expires_at <= now or invitation.status == InvitationStatus.EXPIRED.value:
        invitation.status = InvitationStatus.EXPIRED.value
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVITATION_EXPIRED", "message": "This invitation has expired."},
        )

    if invitation.status != InvitationStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_INVITATION_STATUS",
                "message": f"Invitation has already been {invitation.status}.",
            },
        )

    group = await get_group_or_404(db, invitation.group_id)

    # Check for existing membership
    mem_res = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == current_user.id,
        )
    )
    existing_member = mem_res.scalar_one_or_none()

    if existing_member:
        if existing_member.status == GroupMemberStatus.ACTIVE.value:
            invitation.status = InvitationStatus.ACCEPTED.value
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "ALREADY_MEMBER", "message": "You are already a member of this group."},
            )
        existing_member.status = GroupMemberStatus.ACTIVE.value
        existing_member.role = GroupMemberRole.MEMBER.value
        existing_member.joined_at = now
        existing_member.updated_at = now
    else:
        new_member = GroupMember(
            group_id=group.id,
            user_id=current_user.id,
            role=GroupMemberRole.MEMBER.value,
            status=GroupMemberStatus.ACTIVE.value,
            joined_at=now,
            updated_at=now,
        )
        db.add(new_member)

    invitation.status = InvitationStatus.ACCEPTED.value
    await db.commit()

    updated_group = await get_group_or_404(db, group.id)
    payload = _group_payload(updated_group, current_user)
    # The inviter hears "accepted"; everyone else active hears "joined" (no double notice).
    await notify_users(
        [invitation.created_by], current_user.id, "invitation_accepted",
        str(invitation.id), {**payload, "invitation_id": str(invitation.id)},
        group_id=group.id,
    )
    await _notify_member_joined(db, updated_group, current_user, now, exclude=[invitation.created_by])
    return format_group_response(updated_group, current_user.id)


async def decline_invitation(
    db: AsyncSession,
    invitation_id: uuid.UUID,
    current_user: User,
) -> None:
    """Invited user declines an invitation."""
    user_email = current_user.email.strip().lower()
    result = await db.execute(
        select(GroupInvitation).where(GroupInvitation.id == invitation_id)
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVITATION_NOT_FOUND", "message": "Invitation not found."},
        )

    matches_user = invitation.invited_user_id == current_user.id
    matches_email = (
        invitation.invited_email and invitation.invited_email.strip().lower() == user_email
    )
    if not matches_user and not matches_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INVITATION_NOT_FOUND", "message": "Invitation not found."},
        )

    if invitation.status != InvitationStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_INVITATION_STATUS",
                "message": f"Invitation has already been {invitation.status}.",
            },
        )

    invitation.status = InvitationStatus.DECLINED.value
    await db.commit()

    try:
        group = await get_group_or_404(db, invitation.group_id)
        await notify_users(
            [invitation.created_by], current_user.id, "invitation_declined",
            str(invitation.id),
            {**_group_payload(group, current_user), "invitation_id": str(invitation.id)},
            group_id=group.id,
        )
    except Exception:  # noqa: BLE001 - the decline is already committed
        logger.exception("Decline notification failed after commit; decline kept.")

