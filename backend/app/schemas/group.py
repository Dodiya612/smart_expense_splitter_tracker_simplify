import uuid
from datetime import datetime
from typing import Any, List, Optional
from pydantic import EmailStr, Field, field_validator

from app.models.group import (
    GroupMemberRole,
    GroupMemberStatus,
    GroupType,
    InvitationStatus,
)
from app.schemas.common import BaseSchema


class GroupCreateRequest(BaseSchema):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    type: GroupType

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                raise ValueError("Group name cannot be blank.")
            return v_stripped
        return v

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip() or None
        return v


class GroupUpdateRequest(BaseSchema):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                raise ValueError("Group name cannot be blank.")
            return v_stripped
        return v


class GroupMemberResponse(BaseSchema):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
    status: str
    joined_at: datetime


class GroupResponse(BaseSchema):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    type: str
    created_by: uuid.UUID
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    members: List[GroupMemberResponse] = []
    current_user_role: Optional[str] = None
    join_code: Optional[str] = None


class GroupListItemResponse(BaseSchema):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    type: str
    created_by: uuid.UUID
    created_at: datetime
    member_count: int
    current_user_role: str


class JoinGroupRequest(BaseSchema):
    code: str = Field(..., min_length=6, max_length=32)

    @field_validator("code", mode="before")
    @classmethod
    def sanitize_code(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().upper()
        return v


class JoinCodeResponse(BaseSchema):
    group_id: uuid.UUID
    code: str
    expires_at: datetime


class CreateInvitationRequest(BaseSchema):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    user_id: Optional[uuid.UUID] = None

    @field_validator("phone", mode="before")
    @classmethod
    def sanitize_phone(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_stripped = v.strip()
            return v_stripped or None
        return v


class InvitationResponse(BaseSchema):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    group_type: str
    status: str
    invited_user_id: Optional[uuid.UUID] = None
    invited_email: Optional[str] = None
    invited_phone: Optional[str] = None
    created_by: uuid.UUID
    expires_at: datetime
    created_at: datetime


class JoinGroupResponse(BaseSchema):
    message: str
    group: GroupResponse

