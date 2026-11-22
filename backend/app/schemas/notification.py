"""Notification schemas (US-38 / T-36).

Serialised in snake_case (plain BaseModel), like the balances and settlements
schemas, so the mobile client reads ``created_at`` / ``read_at`` directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.notification import NOTIFICATION_KINDS, SECURITY_KINDS


class NotificationSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)


class NotificationResponse(NotificationSchema):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    payload: dict[str, Any] = Field(default_factory=dict)
    group_id: uuid.UUID | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(NotificationSchema):
    items: list[NotificationResponse]
    next_cursor: str | None = Field(
        None, description="Pass as `cursor` to fetch the next (older) page; null on the last page."
    )
    unread_count: int


class UnreadCountResponse(NotificationSchema):
    unread_count: int


class MarkAllReadResponse(NotificationSchema):
    updated: int


class NotificationPreferenceItem(NotificationSchema):
    kind: str
    enabled: bool


class NotificationPreferenceResponse(NotificationPreferenceItem):
    can_disable: bool = Field(True, description="False for security notices that cannot be switched off.")


class NotificationPreferencesResponse(NotificationSchema):
    preferences: list[NotificationPreferenceResponse]


class NotificationPreferencesUpdateRequest(NotificationSchema):
    model_config = ConfigDict(extra="forbid")

    preferences: list[NotificationPreferenceItem] = Field(min_length=1, max_length=len(NOTIFICATION_KINDS))

    @field_validator("preferences")
    @classmethod
    def _valid_kinds(cls, items: list[NotificationPreferenceItem]) -> list[NotificationPreferenceItem]:
        seen: set[str] = set()
        for item in items:
            if item.kind not in NOTIFICATION_KINDS:
                raise ValueError(f"Unknown notification kind: {item.kind}")
            if item.kind in seen:
                raise ValueError(f"Duplicate notification kind: {item.kind}")
            if item.kind in SECURITY_KINDS and not item.enabled:
                raise ValueError(f"{item.kind} notices cannot be switched off.")
            seen.add(item.kind)
        return items
