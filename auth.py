import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_session_id, get_current_user, get_current_user_optional
from app.api.rate_limit_deps import limit_by_ip, limit_by_user
from app.core.authorization import Action, SessionPolicy
from app.core.config import settings
from app.core.database import get_db
from app.core.password_strength import (
    MIN_PASSWORD_LENGTH,
    MIN_PASSWORD_SCORE,
    estimate_password_strength,
)
from app.core.rate_limiter import (
    RATE_LIMIT_RESPONSES,
    clear,
    get_client_ip,
    get_policy,
    refund,
    reserve,
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
    ChangePasswordRequest,
    ChangePasswordResponse,
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
from app.services import notifications, recurring_service

router = APIRouter()

LOGIN_LIMIT_MESSAGE = "Too many failed login attempts. Please try again in {n} seconds."


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
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        session_id=family_id,
        token_version=user.token_version or 0,
    )

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
    dependencies=[Depends(limit_by_ip("signup_ip"))],
    responses=RATE_LIMIT_RESPONSES,
    summary="Register a new user account (canonical)",
)
async def signup(payload: UserSignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    return await _handle_signup(payload, db)


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_ip("signup_ip"))],
    responses=RATE_LIMIT_RESPONSES,
    summary="Register a new user account (alias)",
)
async def register(payload: UserSignupRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    return await _handle_signup(payload, db)


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    responses=RATE_LIMIT_RESPONSES,
    summary="Authenticate user and issue token pair",
)
async def login(
    request: Request, payload: UserLoginRequest, db: AsyncSession = Depends(get_db)
) -> AuthResponse:
    normalized_email = payload.email.strip().lower()

    # T-39: reserve a slot in each login counter BEFORE checking the password, so parallel
    # guesses cannot all pass a read-then-write check. Fails closed (HTTP 503) if the shared
    # counters are unavailable. The per-account ceiling always applies; the per-(account,
    # address) limit and the per-address ceiling need a verified client address, so they are
    # skipped (with a startup warning) until TRUSTED_CLIENT_IP_HEADER is configured.
    client_ip = get_client_ip(request)
    pair_policy = get_policy("login_pair")
    pair_id = f"{normalized_email}|{client_ip}"
    checks = [(get_policy("login_account"), normalized_email)]
    if client_ip is not None:
        checks += [(pair_policy, pair_id), (get_policy("login_ip"), client_ip)]
    login_hits = await reserve(checks, message=LOGIN_LIMIT_MESSAGE)

    # T-50: FOR SHARE on the user row until this login commits. A concurrent password
    # change holds FOR UPDATE on the same row, so either this login waits and then checks
    # the NEW hash, or the change waits and then sees (and revokes) the session created
    # here. Without it, a login with the old password could slip past the revocation.
    result = await db.execute(
        select(User).where(User.email == normalized_email).with_for_update(read=True)
    )
    user = result.scalar_one_or_none()

    if not user:
        # Preempt user enumeration via timing attack equalization
        verify_dummy_password(payload.password)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid email or password.",
            },
        )

    if not verify_password(payload.password, user.hashed_password):
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

    # Only after the session is saved (if saving fails, every attempt stays counted, US-34):
    #  * clear the account-and-address counter and the account-only counter for this account;
    #  * give just this one successful attempt back to the address-wide ceiling (that bucket is
    #    shared by other users behind the same address and is NOT cleared).
    await refund(login_hits, {"login_ip"})
    await clear(get_policy("login_account"), normalized_email)
    if client_ip is not None:
        await clear(pair_policy, pair_id)

    # T-44: create this user's missed recurring expenses. Time-limited and never raises,
    # so a slow or failing generator cannot delay or break a successful login.
    await recurring_service.catch_up_after_login(user.id)

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        session_id=family_id,
        token_version=user.token_version or 0,
    )

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
    dependencies=[Depends(limit_by_ip("refresh_ip"))],
    responses=RATE_LIMIT_RESPONSES,
    summary="Rotate refresh token and issue new access token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenRefreshResponse:
    token_hash = hash_refresh_token(payload.refresh_token)

    # T-50: lock the owner's user row (FOR SHARE) BEFORE the token row, the same order as
    # change-password (user, then tokens), so the two serialize without deadlocking. A
    # refresh racing a password change therefore either finishes first (and its new token
    # is revoked by the change) or waits and finds its token already revoked.
    peek = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    peeked_token = peek.scalar_one_or_none()
    if peeked_token is not None:
        await db.execute(
            select(User).where(User.id == peeked_token.user_id).with_for_update(read=True)
        )

    query = (
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
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

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        session_id=current_token.family_id,
        token_version=user.token_version or 0,
    )

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


# --------------------------------------------------------------------------------------
# T-50: change password
# --------------------------------------------------------------------------------------


def _password_rule_error(code: str, message: str, hints: tuple[str, ...] = ()) -> HTTPException:
    detail: dict[str, object] = {"code": code, "message": message}
    if hints:
        detail["detail"] = [
            {"loc": ["body", "newPassword"], "msg": hint, "type": code.lower()} for hint in hints
        ]
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _validate_new_password(payload: ChangePasswordRequest, user: User) -> None:
    """New-password rules, checked before any hashing. Messages never contain a password."""
    new_password = payload.new_password
    if new_password != payload.confirm_new_password:
        raise _password_rule_error(
            "PASSWORD_MISMATCH", "The new password and its confirmation do not match."
        )
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise _password_rule_error(
            "PASSWORD_TOO_SHORT",
            f"The new password must be at least {MIN_PASSWORD_LENGTH} characters long.",
        )
    strength = estimate_password_strength(new_password, (user.name, user.email))
    if strength.score < MIN_PASSWORD_SCORE:
        raise _password_rule_error(
            "WEAK_PASSWORD",
            f"The new password is too weak (strength {strength.score}/4; "
            f"at least {MIN_PASSWORD_SCORE}/4 is required).",
            strength.feedback,
        )


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(limit_by_user("password_change_user"))],
    responses=RATE_LIMIT_RESPONSES,
    summary="Change the authenticated user's password and sign out every other device",
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session_id: uuid.UUID = Depends(get_current_session_id),
    db: AsyncSession = Depends(get_db),
) -> ChangePasswordResponse:
    """Verify the current password, store the new one and revoke every other session.

    Only the authenticated user's own password can change: the account comes from the
    validated access token, never from the request body. In ONE transaction it:

    * locks the user row and verifies ``current_password`` against the locked hash;
    * stores the Argon2id hash of the new password and increments ``token_version``, which
      makes every access token issued before now invalid on its next use (all devices);
    * revokes every unrevoked refresh token of the user: other devices can no longer
      refresh, and this device's refresh token is rotated within its family.

    This device gets a fresh token pair in the response and stays signed in. The
    ``password_changed`` notice is stored only after the commit succeeds.
    """
    _validate_new_password(payload, current_user)

    user_result = await db.execute(
        select(User)
        .where(User.id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Authentication required."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 400, not 401: a 401 tells the client its session is invalid (it would refresh and
    # retry). A wrong current password is a form error on a valid session.
    if not verify_password(payload.current_password, user.hashed_password):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_CURRENT_PASSWORD",
                "message": "Your current password is incorrect.",
            },
        )
    if verify_password(payload.new_password, user.hashed_password):
        await db.rollback()
        raise _password_rule_error(
            "PASSWORD_UNCHANGED", "The new password must be different from your current password."
        )

    now = datetime.now(timezone.utc)
    token_result = await db.execute(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.is_revoked.is_(False),
        )
        .with_for_update()
    )
    active_tokens = list(token_result.scalars().all())
    current_tokens = [
        t for t in active_tokens if t.family_id == session_id and t.expires_at > now
    ]
    if not current_tokens:
        # This device's session was already revoked or has expired.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_REVOKED",
                "message": "This session has been signed out. Please log in again.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    other_sessions = {
        t.family_id for t in active_tokens if t.family_id != session_id and t.expires_at > now
    }
    for token in active_tokens:
        token.is_revoked = True

    parent = max(current_tokens, key=lambda t: t.created_at or now)
    parent.last_seen = now
    remember = bool(parent.remember)
    if remember:
        new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    else:
        new_expires_at = now + timedelta(hours=settings.REFRESH_TOKEN_EXPIRE_HOURS_WITHOUT_REMEMBER)
    new_raw_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=session_id,
            token_hash=hash_refresh_token(new_raw_token),
            parent_id=parent.id,
            is_revoked=False,
            expires_at=new_expires_at,
            remember=remember,
            device_label=parent.device_label,
            last_seen=now,
            created_at=now,
        )
    )

    user.hashed_password = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    user.updated_at = now
    new_token_version = user.token_version
    await db.commit()

    # After the commit only: a failed change never produces a notice, and a notice failure
    # is logged and swallowed by the service (the password change itself has succeeded).
    await notifications.emit(
        user.id,
        "password_changed",
        ref=f"tv{new_token_version}",
        dedupe_key=f"password_changed:{uuid.uuid4()}",
        payload={"revoked_sessions": len(other_sessions)},
    )

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        session_id=session_id,
        token_version=new_token_version,
    )
    return ChangePasswordResponse(
        message="Your password has been changed.",
        tokens=TokenBundle(
            access_token=access_token,
            refresh_token=new_raw_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
        revoked_sessions=len(other_sessions),
    )
