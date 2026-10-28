import uuid
import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    AuthResponse,
    LogoutRequest,
    MessageResponse,
    RefreshTokenRequest,
    TokenBundle,
    TokenRefreshResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)


def test_user_signup_request_valid_and_normalization():
    data = {
        "name": "  Test User  ",
        "email": "  TEST.USER@EXAMPLE.COM  ",
        "password": "SecurePassword123!",
    }
    req = UserSignupRequest.model_validate(data)
    assert req.name == "Test User"
    assert req.email == "test.user@example.com"
    assert req.password == "SecurePassword123!"


def test_user_signup_request_invalid_email():
    with pytest.raises(ValidationError):
        UserSignupRequest(
            name="Test User",
            email="not-an-email",
            password="SecurePassword123!",
        )


def test_user_signup_request_password_bounds():
    # Min length 8
    with pytest.raises(ValidationError):
        UserSignupRequest(
            name="Test User",
            email="test@example.com",
            password="short",
        )

    # Max length 128
    with pytest.raises(ValidationError):
        UserSignupRequest(
            name="Test User",
            email="test@example.com",
            password="a" * 129,
        )

    # Valid boundary lengths
    valid_8 = UserSignupRequest(
        name="Test",
        email="test@example.com",
        password="a" * 8,
    )
    assert len(valid_8.password) == 8

    valid_128 = UserSignupRequest(
        name="Test",
        email="test@example.com",
        password="a" * 128,
    )
    assert len(valid_128.password) == 128


def test_user_signup_request_name_bounds():
    # Name min 1
    with pytest.raises(ValidationError):
        UserSignupRequest(
            name="",
            email="test@example.com",
            password="SecurePassword123!",
        )

    # Name max 100
    with pytest.raises(ValidationError):
        UserSignupRequest(
            name="a" * 101,
            email="test@example.com",
            password="SecurePassword123!",
        )


def test_user_login_request_normalization():
    req = UserLoginRequest(
        email="  LOGIN@EXAMPLE.COM ",
        password="SomePassword",
    )
    assert req.email == "login@example.com"
    assert req.password == "SomePassword"


def test_refresh_token_request_aliases():
    # Wire camelCase format
    req1 = RefreshTokenRequest.model_validate({"refreshToken": "sample-token-abc"})
    assert req1.refresh_token == "sample-token-abc"

    # Python snake_case format
    req2 = RefreshTokenRequest.model_validate({"refresh_token": "sample-token-abc"})
    assert req2.refresh_token == "sample-token-abc"


def test_logout_request_optional_payload():
    req_empty = LogoutRequest.model_validate({})
    assert req_empty.refresh_token is None

    req_none = LogoutRequest.model_validate({"refreshToken": None})
    assert req_none.refresh_token is None

    req_with_token = LogoutRequest.model_validate({"refreshToken": "some-token"})
    assert req_with_token.refresh_token == "some-token"

    # Whitespace-only or empty strings are sanitized to None
    req_whitespace = LogoutRequest.model_validate({"refreshToken": "   "})
    assert req_whitespace.refresh_token is None

    req_empty_str = LogoutRequest.model_validate({"refreshToken": ""})
    assert req_empty_str.refresh_token is None


def test_user_response_uuid_conversion():
    user_uuid = uuid.uuid4()
    resp = UserResponse(
        id=user_uuid,  # pyright: ignore
        name="Alice",
        email="alice@example.com",
    )
    assert resp.id == str(user_uuid)
    assert isinstance(resp.id, str)

    # Wire format serialization
    dumped = resp.model_dump(by_alias=True)
    assert dumped == {
        "id": str(user_uuid),
        "name": "Alice",
        "email": "alice@example.com",
    }


def test_token_bundle_and_auth_response_camel_case_wire_format():
    user_uuid = uuid.uuid4()
    user_resp = UserResponse(id=str(user_uuid), name="Bob", email="bob@example.com")
    tokens = TokenBundle(
        access_token="acc-123",
        refresh_token="ref-456",
        token_type="bearer",
        expires_in=900,
    )
    auth_resp = AuthResponse(user=user_resp, tokens=tokens)

    wire_dict = auth_resp.model_dump(by_alias=True)
    assert "user" in wire_dict
    assert "tokens" in wire_dict
    assert wire_dict["tokens"]["accessToken"] == "acc-123"
    assert wire_dict["tokens"]["refreshToken"] == "ref-456"
    assert wire_dict["tokens"]["tokenType"] == "bearer"
    assert wire_dict["tokens"]["expiresIn"] == 900


def test_token_refresh_response_wire_format():
    resp = TokenRefreshResponse(
        access_token="new-acc",
        refresh_token="new-ref",
        token_type="bearer",
        expires_in=900,
    )
    dumped = resp.model_dump(by_alias=True)
    assert dumped == {
        "accessToken": "new-acc",
        "refreshToken": "new-ref",
        "tokenType": "bearer",
        "expiresIn": 900,
    }


def test_message_response():
    resp = MessageResponse(message="Success")
    assert resp.message == "Success"
    assert resp.model_dump(by_alias=True) == {"message": "Success"}


def test_refresh_token_request_empty_rejected():
    with pytest.raises(ValidationError):
        RefreshTokenRequest(refresh_token="")

