import hashlib
import uuid
from datetime import timedelta
import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    validate_password_length,
    verify_dummy_password,
    verify_password,
)


def test_password_hashing_and_verification():
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    # Must be argon2id with specified parameters
    assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(password, "invalid_hash_string") is False


def test_password_length_validation():
    # Min length: 8
    with pytest.raises(ValueError, match="at least 8 characters"):
        validate_password_length("1234567")

    assert validate_password_length("12345678") is True

    # Max length: 128
    assert validate_password_length("a" * 128) is True
    with pytest.raises(ValueError, match="not exceed 128 characters"):
        validate_password_length("a" * 129)


def test_dummy_timing_equalization():
    # Calling dummy verify should always return False and execute without error
    result = verify_dummy_password("nonexistent_user_attempt")
    assert result is False


def test_jwt_create_and_decode_valid():
    user_id = uuid.uuid4()
    email = "user@example.com"

    token = create_access_token(user_id=user_id, email=email)
    assert isinstance(token, str)

    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["email"] == email
    assert payload["type"] == "access"
    assert payload["iss"] == settings.JWT_ISSUER
    assert payload["aud"] == settings.JWT_AUDIENCE
    assert "iat" in payload
    assert "exp" in payload
    assert "jti" in payload


def test_jwt_expired_token_rejection():
    user_id = uuid.uuid4()
    email = "expired@example.com"

    expired_token = create_access_token(
        user_id=user_id,
        email=email,
        expires_delta=timedelta(seconds=-10),
    )

    with pytest.raises(TokenExpiredError, match="expired"):
        decode_access_token(expired_token)


def test_jwt_tampered_token_rejection():
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, email="user@example.com")

    # Tamper with signature
    tampered_token = token[:-4] + "abcd"
    with pytest.raises(TokenInvalidError):
        decode_access_token(tampered_token)


def test_jwt_invalid_issuer_and_audience():
    user_id = uuid.uuid4()

    # Encode with wrong issuer
    payload = {
        "sub": str(user_id),
        "email": "test@example.com",
        "type": "access",
        "iss": "unauthorized-issuer",
        "aud": settings.JWT_AUDIENCE,
        "exp": 9999999999,
    }
    bad_issuer_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(TokenInvalidError):
        decode_access_token(bad_issuer_token)

    # Encode with wrong audience
    payload["iss"] = settings.JWT_ISSUER
    payload["aud"] = "unauthorized-audience"
    bad_aud_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(TokenInvalidError):
        decode_access_token(bad_aud_token)


def test_jwt_invalid_type_claim():
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "email": "test@example.com",
        "type": "refresh",  # Not "access"
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "exp": 9999999999,
    }
    wrong_type_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(TokenInvalidError, match="expected 'access'"):
        decode_access_token(wrong_type_token)


def test_refresh_token_generation_and_hashing():
    token1 = generate_refresh_token()
    token2 = generate_refresh_token()

    assert len(token1) == 64
    assert len(token2) == 64
    assert token1 != token2

    hashed1 = hash_refresh_token(token1)
    hashed2 = hash_refresh_token(token2)

    assert len(hashed1) == 64
    assert len(hashed2) == 64
    assert hashed1 != hashed2

    # Deterministic SHA-256 verification
    expected_hash = hashlib.sha256(token1.encode("utf-8")).hexdigest()
    assert hashed1 == expected_hash


def test_jwt_missing_sub_claim():
    payload = {
        "email": "test@example.com",
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "exp": 9999999999,
    }
    token_no_sub = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(TokenInvalidError, match="sub"):
        decode_access_token(token_no_sub)


def test_jwt_malformed_and_empty_token():
    with pytest.raises(TokenInvalidError):
        decode_access_token("")

    with pytest.raises(TokenInvalidError):
        decode_access_token("not-a-valid-jwt-token")

    with pytest.raises(TokenInvalidError):
        decode_access_token("a.b.c.d.e")


def test_jwt_signature_with_wrong_key_rejected():
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "email": "wrongkey@example.com",
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "exp": 9999999999,
    }
    forged_token = jwt.encode(payload, "completely-different-secret-key-32-bytes-long", algorithm="HS256")
    with pytest.raises(TokenInvalidError):
        decode_access_token(forged_token)


def test_jwt_none_algorithm_rejected():
    user_id = uuid.uuid4()
    payload = {
        "sub": str(user_id),
        "email": "nonealg@example.com",
        "type": "access",
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "exp": 9999999999,
    }
    none_token = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(TokenInvalidError):
        decode_access_token(none_token)


