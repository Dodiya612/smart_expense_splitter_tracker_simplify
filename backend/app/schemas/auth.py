import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import EmailStr, Field, field_validator
from app.schemas.common import BaseSchema


class UserSignupRequest(BaseSchema):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    remember_me: bool = False
    device_label: Optional[str] = Field(None, max_length=150)

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class UserLoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(..., min_length=1)
    remember_me: bool = False
    device_label: Optional[str] = Field(None, max_length=150)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class RefreshTokenRequest(BaseSchema):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseSchema):
    refresh_token: Optional[str] = None

    @field_validator("refresh_token", mode="before")
    @classmethod
    def sanitize_refresh_token(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_stripped = v.strip()
            return v_stripped if v_stripped else None
        return v


class UserResponse(BaseSchema):
    id: str
    name: str
    email: str

    @field_validator("id", mode="before")
    @classmethod
    def convert_id(cls, v: Any) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)


class TokenBundle(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class AuthResponse(BaseSchema):
    user: UserResponse
    tokens: TokenBundle


class TokenRefreshResponse(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900


class MessageResponse(BaseSchema):
    message: str


class SessionResponse(BaseSchema):
    id: str
    device_label: Optional[str] = None
    created_at: datetime
    last_seen: datetime
    expires_at: datetime
    remember: bool = False
    is_current: bool = False

    @field_validator("id", mode="before")
    @classmethod
    def convert_id(cls, v: Any) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)


class SessionListResponse(BaseSchema):
    sessions: List[SessionResponse]
