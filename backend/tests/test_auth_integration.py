import uuid
from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.core.rate_limit import (
    check_login_rate_limit,
    record_failed_login_attempt,
    reset_login_rate_limit,
)
from app.core.security import hash_password, hash_refresh_token, verify_password
from app.models.rate_limit import LoginRateLimit
from app.models.refresh_token import RefreshToken
from app.models.user import User


@pytest.fixture(autouse=True)
async def dispose_engine_after_test():
    """Ensure all connections tied to the test event loop are cleanly disposed."""
    yield
    await engine.dispose()


async def _check_tables_exist() -> bool:
    """Helper to detect if Phase 2 auth tables have been migrated to the database."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT to_regclass('public.users'), to_regclass('public.refresh_tokens'), to_regclass('public.login_rate_limits')")
            )
            users_table, tokens_table, rate_limits_table = result.one()
            return bool(users_table and tokens_table and rate_limits_table)
    except Exception:
        return False


@pytest.mark.anyio
async def test_auth_tables_schema_live_postgres():
    """
    Designated for live Supabase verification once migrations are applied in Checkpoint D.
    Verifies the existence and column structure of 'users' and 'refresh_tokens' tables.
    """
    if not await _check_tables_exist():
        pytest.skip("Live auth tables ('users', 'refresh_tokens') not yet migrated (deferred to Checkpoint D).")

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        assert "users" in tables
        assert "refresh_tokens" in tables
        assert "login_rate_limits" in tables

        user_cols = await conn.run_sync(lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("users")})
        expected_user_cols = {"id", "email", "name", "hashed_password", "is_active", "created_at", "updated_at"}
        assert expected_user_cols.issubset(user_cols)

        token_cols = await conn.run_sync(lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("refresh_tokens")})
        expected_token_cols = {"id", "user_id", "family_id", "token_hash", "parent_id", "is_revoked", "expires_at", "created_at"}
        assert expected_token_cols.issubset(token_cols)

        rate_limit_cols = await conn.run_sync(lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("login_rate_limits")})
        expected_rate_limit_cols = {"id", "key", "attempts", "last_attempt_at", "created_at", "updated_at"}
        assert expected_rate_limit_cols.issubset(rate_limit_cols)

        # Verify canonical unique index on key without redundant indexes
        rate_limit_indexes = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_indexes("login_rate_limits"))
        ix_map = {ix["name"]: ix for ix in rate_limit_indexes}
        assert "ix_login_rate_limits_key" in ix_map
        assert ix_map["ix_login_rate_limits_key"]["unique"] is True
        assert "login_rate_limits_key_key" not in ix_map, "Redundant unique constraint index must not exist"


@pytest.mark.anyio
async def test_live_supabase_auth_cascade_and_rotation():
    """
    Live integration test designated for Checkpoint D.
    Tests full user creation, Argon2id verification in PostgreSQL,
    refresh token creation, and ON DELETE CASCADE on foreign key.
    """
    if not await _check_tables_exist():
        pytest.skip("Live auth tables not yet migrated (deferred to Checkpoint D).")

    async with AsyncSessionLocal() as session:
        # Create test user
        test_email = f"live_test_{uuid.uuid4().hex[:8]}@example.com"
        raw_password = "LiveSecurePassword123!"
        user = User(
            email=test_email,
            name="Live Integration User",
            hashed_password=hash_password(raw_password),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        # Add refresh token
        family_id = uuid.uuid4()
        token_hash = hash_refresh_token(uuid.uuid4().hex)
        refresh_token = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash,
            parent_id=None,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(refresh_token)
        await session.commit()

        # Verify read and password verification from live DB
        db_user = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert db_user.email == test_email
        assert verify_password(raw_password, db_user.hashed_password) is True

        # Test CASCADE deletion
        await session.delete(db_user)
        await session.commit()

        tokens_left = (await session.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )).scalars().all()
        assert len(tokens_left) == 0, "RefreshToken rows should be deleted via ON DELETE CASCADE"


@pytest.mark.anyio
async def test_live_postgresql_refresh_token_reuse_detection():
    """
    Live PostgreSQL integration test for token reuse detection.
    Verifies that presenting an already-revoked token invalidates all tokens in the family.
    """
    if not await _check_tables_exist():
        pytest.skip("Live auth tables not yet migrated (deferred to Checkpoint D).")

    async with AsyncSessionLocal() as session:
        test_email = f"reuse_test_{uuid.uuid4().hex[:8]}@example.com"
        user = User(
            email=test_email,
            name="Reuse Test User",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        family_id = uuid.uuid4()
        token1_raw = uuid.uuid4().hex
        token1_hash = hash_refresh_token(token1_raw)
        t1 = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=token1_hash,
            parent_id=None,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(t1)
        await session.commit()

        # Step 1: Legitimate rotation (T1 -> T2)
        token2_raw = uuid.uuid4().hex
        token2_hash = hash_refresh_token(token2_raw)
        t1_fetched = (await session.execute(
            select(RefreshToken).where(RefreshToken.id == t1.id).with_for_update()
        )).scalar_one()
        t1_fetched.is_revoked = True

        t2 = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=token2_hash,
            parent_id=t1.id,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(t2)
        await session.commit()

        # Step 2: Attacker or replayed request presents T1
        replayed_hash = hash_refresh_token(token1_raw)
        replayed_token = (await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == replayed_hash).with_for_update()
        )).scalar_one()

        assert replayed_token.is_revoked is True
        # Reuse detected -> Revoke entire family
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == replayed_token.family_id)
            .values(is_revoked=True)
        )
        await session.commit()

        # Step 3: Verify child token T2 is now also revoked
        t2_fetched = (await session.execute(
            select(RefreshToken).where(RefreshToken.id == t2.id)
        )).scalar_one()
        assert t2_fetched.is_revoked is True

        # Cleanup
        await session.delete(user)
        await session.commit()


@pytest.mark.anyio
async def test_live_postgresql_concurrent_refresh_row_locking():
    """
    Live PostgreSQL integration test simulating two concurrent refresh attempts
    using real PostgreSQL row-level locks (SELECT ... FOR UPDATE).
    Verifies that exactly one succeeds and the other triggers reuse detection.
    """
    if not await _check_tables_exist():
        pytest.skip("Live auth tables not yet migrated (deferred to Checkpoint D).")

    import asyncio

    # Setup user and initial refresh token
    async with AsyncSessionLocal() as session:
        test_email = f"concurrent_test_{uuid.uuid4().hex[:8]}@example.com"
        user = User(
            email=test_email,
            name="Concurrent Test User",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        raw_token = uuid.uuid4().hex
        token_hash = hash_refresh_token(raw_token)
        family_id = uuid.uuid4()
        token = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            token_hash=token_hash,
            parent_id=None,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        session.add(token)
        await session.commit()
        user_id = user.id

    async def attempt_refresh() -> str:
        async with AsyncSessionLocal() as s:
            try:
                # Lock row with FOR UPDATE
                q = select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
                res = await s.execute(q)
                curr = res.scalar_one_or_none()
                if not curr:
                    return "not_found"
                if curr.is_revoked:
                    # Reuse detected: invalidate family
                    await s.execute(
                        update(RefreshToken)
                        .where(RefreshToken.family_id == curr.family_id)
                        .values(is_revoked=True)
                    )
                    await s.commit()
                    return "reuse_detected"

                # Valid rotation
                curr.is_revoked = True
                new_child = RefreshToken(
                    user_id=curr.user_id,
                    family_id=curr.family_id,
                    token_hash=hash_refresh_token(uuid.uuid4().hex),
                    parent_id=curr.id,
                    is_revoked=False,
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                )
                s.add(new_child)
                await s.commit()
                return "rotated"
            except Exception as e:
                await s.rollback()
                return f"error: {e}"

    # Fire both concurrently
    results = await asyncio.gather(attempt_refresh(), attempt_refresh())
    assert set(results) == {"rotated", "reuse_detected"}, f"Expected one rotated and one reuse_detected, got {results}"

    # Cleanup
    async with AsyncSessionLocal() as session:
        db_user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if db_user:
            await session.delete(db_user)
            await session.commit()


@pytest.mark.anyio
async def test_live_postgresql_duplicate_email_uniqueness_constraint():
    """
    Live PostgreSQL integration test:
    Verify that registering duplicate normalized emails cannot create duplicate accounts
    and that the database uniqueness constraint (ix_users_email) is strictly enforced.
    """
    if not await _check_tables_exist():
        pytest.skip("Live auth tables not yet migrated.")

    test_email = f"unique_test_{uuid.uuid4().hex[:8]}@example.com"

    async with AsyncSessionLocal() as session:
        # Insert first user with normalized email
        user1 = User(
            email=test_email,
            name="First User",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        session.add(user1)
        await session.commit()
        user1_id = user1.id

    # Attempt to insert second user with exact same email into PostgreSQL
    async with AsyncSessionLocal() as session2:
        user2 = User(
            email=test_email,
            name="Second User (Duplicate)",
            hashed_password=hash_password("Password123!"),
            is_active=True,
        )
        session2.add(user2)
        with pytest.raises(IntegrityError) as exc_info:
            await session2.commit()
        assert "unique constraint" in str(exc_info.value).lower() or "ix_users_email" in str(exc_info.value).lower()

    # Cleanup test user
    async with AsyncSessionLocal() as session:
        db_user = (await session.execute(select(User).where(User.id == user1_id))).scalar_one_or_none()
        if db_user:
            await session.delete(db_user)
            await session.commit()


@pytest.mark.anyio
async def test_live_postgresql_login_rate_limiting_shared_persistence():
    """
    Live PostgreSQL integration test:
    Verifies that rate limiting state is stored in PostgreSQL and shared across
    independent database sessions (multi-worker / multi-instance simulation).
    """
    if not await _check_tables_exist():
        pytest.skip("Live auth tables not yet migrated.")

    test_key = f"rate_limit_test_{uuid.uuid4().hex[:8]}@example.com"

    try:
        # Worker/Instance 1: Records 3 failed attempts in its session
        async with AsyncSessionLocal() as worker1_session:
            for _ in range(3):
                await record_failed_login_attempt(worker1_session, test_key)

        # Worker/Instance 2: Reads state, confirms 3 attempts recorded, adds 2 more (total 5)
        async with AsyncSessionLocal() as worker2_session:
            record = (await worker2_session.execute(
                select(LoginRateLimit).where(LoginRateLimit.key == test_key)
            )).scalar_one_or_none()
            assert record is not None
            assert record.attempts == 3

            for _ in range(2):
                await record_failed_login_attempt(worker2_session, test_key)

        # Worker/Instance 3: Checks rate limit (threshold = 5). Must raise HTTP 429
        async with AsyncSessionLocal() as worker3_session:
            with pytest.raises(HTTPException) as exc_info:
                await check_login_rate_limit(worker3_session, test_key, max_attempts=5)
            assert exc_info.value.status_code == 429
            assert exc_info.value.detail["code"] == "RATE_LIMIT_EXCEEDED"

        # Worker/Instance 1: Resets rate limit (simulating successful login)
        async with AsyncSessionLocal() as worker1_session:
            await reset_login_rate_limit(worker1_session, test_key)

        # Worker/Instance 2: Confirms lock is cleared, check passes without 429
        async with AsyncSessionLocal() as worker2_session:
            # Does not raise HTTPException
            await check_login_rate_limit(worker2_session, test_key, max_attempts=5)

    finally:
        # Cleanup test rate limit record
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("DELETE FROM login_rate_limits WHERE key = :k"),
                {"k": test_key},
            )
            await session.commit()


