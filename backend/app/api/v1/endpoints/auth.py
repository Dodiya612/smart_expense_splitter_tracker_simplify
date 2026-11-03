import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional
from app.core.authorization import Action, SessionPolicy
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import (
    check_login_rate_limit,
    record_failed_login_attempt,
    reset_login_rate_limit,
)
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    validate_password_length,
    verify_dummy_password,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LogoutRequest,
    MessageResponse,
    RefreshTokenRequest,
    SessionListResponse,
    SessionResponse,
    TokenBundle,
    TokenRefreshResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)

router = APIRouter()


async def _handle_signup(payload: UserSignupRequest, db: AsyncSession) -> AuthResponse:
    normalized_email = payload.email.strip().lower()

    # Check if user with normalized email already exists
    existing_user_query = await db.execute(
        select(User).where(User.email == normalized_email)
    )
    if existing_user_query.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_ALREADY_EXISTS",
                "message": "A user with this email address already exists.",
            },
        )

    # Validate password length bounds
    validate_password_length(payload.password)

    # Hash password with Argon2id
    hashed_pw = hash_password(payload.password)

    # Create new user row and initial refresh token within transactional error handling
    try:
        user = User(
            email=normalized_email,
            name=payload.name.strip(),
            hashed_password=hashed_pw,
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # Generate new refresh token with fresh family_id
        raw_refresh_token = generate_refresh_token()
        token_hash = hash_refresh_token(raw_refresh_token)
        family_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if payload.remember_me:
            expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        else:
            expires_at = now + timedelta(hours=settings.REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER)

        refresh_token_row = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash,
            parent_id=None,
            is_revoked=False,
            expires_at=expires_at,
            remember=payload.remember_me,
            device_label=payload.device_label,
            last_seen=now,
            created_at=now,
        )
        db.add(refresh_token_row)
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EMAIL_ALREADY_EXISTS",
                "message": "A user with this email address already exists.",
            },
        )

    # Generate JWT access token
    access_token = create_access_token(user_id=user.id, email=user.email)

    return AuthResponse(
        user=UserResponse(
            id=str(user.id),
            name=user.name,
            email=user.email,
        ),
        tokens=TokenBundle(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
    )


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account (canonical)",
)
async def signup(payload: UserSignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    return await _handle_signup(payload, db)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account (alias)",
)
async def register(payload: UserSignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    return await _handle_signup(payload, db)


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and issue token pair",
)
async def login(payload: UserLoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    normalized_email = payload.email.strip().lower()

    # Pre-auth rate limit check (returns 429 when max failed attempts reached)
    await check_login_rate_limit(db, normalized_email)

    result = await db.execute(
        select(User).where(User.email == normalized_email)
    )
    user = result.scalar_one_or_none()

    if not user:
        # Preempt user enumeration via timing attack equalization
        verify_dummy_password(payload.password)
        await record_failed_login_attempt(db, normalized_email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid email or password.",
            },
        )

    if not verify_password(payload.password, user.hashed_password):
        await record_failed_login_attempt(db, normalized_email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid email or password.",
            },
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "ACCOUNT_INACTIVE",
                "message": "User account is inactive.",
            },
        )

    # Successful login resets the failed login attempt counter
    await reset_login_rate_limit(db, normalized_email)

    # Issue new refresh token with fresh family_id
    raw_refresh_token = generate_refresh_token()
    token_hash = hash_refresh_token(raw_refresh_token)
    family_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    if payload.remember_me:
        expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    else:
        expires_at = now + timedelta(hours=settings.REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER)

    refresh_token_row = RefreshToken(
        user_id=user.id,
        family_id=family_id,
        token_hash=token_hash,
        parent_id=None,
        is_revoked=False,
        expires_at=expires_at,
        remember=payload.remember_me,
        device_label=payload.device_label,
        last_seen=now,
        created_at=now,
    )
    db.add(refresh_token_row)
    await db.commit()

    access_token = create_access_token(user_id=user.id, email=user.email)

    return AuthResponse(
        user=UserResponse(
            id=str(user.id),
            name=user.name,
            email=user.email,
        ),
        tokens=TokenBundle(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
    )


@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token and issue new access token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenRefreshResponse:
    token_hash = hash_refresh_token(payload.refresh_token)

    query = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    result = await db.execute(query)
    current_token = result.scalar_one_or_none()

    if not current_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Invalid refresh token.",
            },
        )

    # Refresh token reuse detection
    if current_token.is_revoked:
        # Revoke all tokens belonging to this family
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == current_token.family_id)
            .values(is_revoked=True)
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_REVOKED",
                "message": "Refresh token has been revoked or reused. All associated sessions have been terminated.",
            },
        )

    now = datetime.now(timezone.utc)
    if current_token.expires_at <= now:
        current_token.is_revoked = True
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_EXPIRED",
                "message": "Refresh token has expired.",
            },
        )

    # Fetch user to verify account exists and is active before rotation
    user_query = await db.execute(
        select(User).where(User.id == current_token.user_id)
    )
    user = user_query.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "User not found.",
            },
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "ACCOUNT_INACTIVE",
                "message": "User account is inactive.",
            },
        )

    # Invalidate the current refresh token and update its last_seen timestamp
    current_token.is_revoked = True
    current_token.last_seen = now

    # Determine child token expiration and metadata from parent policy
    parent_remember = getattr(current_token, "remember", False) or False
    parent_device_label = getattr(current_token, "device_label", None)
    if parent_remember:
        new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    else:
        new_expires_at = now + timedelta(hours=settings.REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER)

    # Generate child refresh token within the same family
    new_raw_token = generate_refresh_token()
    new_token_hash = hash_refresh_token(new_raw_token)

    child_token = RefreshToken(
        user_id=current_token.user_id,
        family_id=current_token.family_id,
        token_hash=new_token_hash,
        parent_id=current_token.id,
        is_revoked=False,
        expires_at=new_expires_at,
        remember=parent_remember,
        device_label=parent_device_label,
        last_seen=now,
        created_at=now,
    )
    db.add(child_token)
    await db.commit()

    access_token = create_access_token(user_id=user.id, email=user.email)

    return TokenRefreshResponse(
        access_token=access_token,
        refresh_token=new_raw_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke refresh token or user sessions",
)
async def logout(
    payload: Optional[LogoutRequest] = None,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    has_refresh_token = bool(payload and payload.refresh_token and payload.refresh_token.strip())

    # Case 1: Both authenticated user AND refresh token provided
    if current_user and has_refresh_token:
        assert payload is not None and payload.refresh_token is not None
        token_hash = hash_refresh_token(payload.refresh_token.strip())
        token_query = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_row = token_query.scalar_one_or_none()
        if token_row:
            # CRITICAL SECURITY CHECK: A user must NEVER be able to revoke another user's session!
            if token_row.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "CREDENTIAL_MISMATCH",
                        "message": "The provided refresh token does not belong to the authenticated user.",
                    },
                )
            # Legitimate matching user: revoke that token's family
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token_row.family_id)
                .values(is_revoked=True)
            )
        else:
            # Token does not exist: idempotent logout, revoke active tokens for current user
            await db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == current_user.id,
                    RefreshToken.is_revoked.is_(False),
                )
                .values(is_revoked=True)
            )

    # Case 2: Only refresh token provided (e.g. access token is expired or absent)
    elif has_refresh_token:
        assert payload is not None and payload.refresh_token is not None
        token_hash = hash_refresh_token(payload.refresh_token.strip())
        token_query = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_row = token_query.scalar_one_or_none()
        if token_row:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token_row.family_id)
                .values(is_revoked=True)
            )

    # Case 3: Only authenticated user provided (no refresh token in body)
    elif current_user:
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == current_user.id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )

    # Case 4: Neither provided: idempotent 200
    # No revocation action needed

    await db.commit()
    return MessageResponse(message="Successfully logged out.")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve current authenticated user profile",
)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
    )


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List active sessions for the authenticated user",
)
async def list_active_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SessionListResponse:
    now = datetime.now(timezone.utc)
    query = (
        select(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.is_revoked.is_(False),
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.last_seen.desc())
    )
    result = await db.execute(query)
    active_tokens = result.scalars().all()

    # Deduplicate by family_id so each device session stream appears once
    seen_families = set()
    sessions: list[SessionResponse] = []
    for token in active_tokens:
        if token.family_id not in seen_families:
            seen_families.add(token.family_id)
            token_created = getattr(token, "created_at", None) or getattr(token, "last_seen", None) or datetime.now(timezone.utc)
            token_last_seen = getattr(token, "last_seen", None) or token_created
            sessions.append(
                SessionResponse(
                    id=str(token.family_id),
                    device_label=token.device_label,
                    created_at=token_created,
                    last_seen=token_last_seen,
                    expires_at=token.expires_at,
                    remember=bool(token.remember),
                    is_current=False,
                )
            )

    return SessionListResponse(sessions=sessions)


@router.delete(
    "/sessions/{session_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke an active session belonging to the authenticated user",
)
async def revoke_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    try:
        target_uuid = uuid.UUID(session_id.strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": "Session not found.",
            },
        )

    # Locate token matching target_uuid as either family_id or token id
    query = select(RefreshToken).where(
        (RefreshToken.family_id == target_uuid) | (RefreshToken.id == target_uuid)
    )
    result = await db.execute(query)
    target_token = result.scalars().first()

    if not target_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SESSION_NOT_FOUND",
                "message": "Session not found.",
            },
        )

    # Enforce strict session ownership via shared authorization policy
    SessionPolicy.authorize(current_user, target_token, Action.DELETE)

    # Revoke all tokens belonging to this family
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == target_token.family_id,
            RefreshToken.user_id == current_user.id,
        )
        .values(is_revoked=True)
    )
    await db.commit()

    return MessageResponse(message="Session successfully revoked.")

