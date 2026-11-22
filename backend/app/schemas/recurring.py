"""Recurring expense schemas (US-14 / T-44).

Money is integer paise (``amount_paise``); floats and booleans are rejected. Dates are
calendar days in Asia/Kolkata. Unknown fields are rejected (422), so ownership fields
such as ``owner_id``/``user_id`` can never be supplied by the client.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, StrictInt, field_validator, model_validator

from app.schemas.common import BaseSchema, to_camel
from app.schemas.expense import validate_paise_amount
from app.schemas.ledger import SplitMode

Frequency = Literal["daily", "weekly", "monthly", "yearly"]
RuleStatus = Literal["active", "paused", "cancelled"]
OccurrenceStatus = Literal["created", "skipped"]

MAX_PAISE = 9_223_372_036_854_775_807  # BIGINT upper bound, as for settlements
MAX_SPLIT_ENTRIES = 100


class _StrictSchema(BaseSchema):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


def _amount(value: Any) -> int:
    paise = validate_paise_amount(value)
    if paise > MAX_PAISE:
        raise ValueError(f"Amount must be at most {MAX_PAISE} paise.")
    return paise


def _clean_description(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Description cannot be empty or only whitespace.")
    return cleaned


class RecurringSplit(_StrictSchema):
    """How a group rule's expense is paid and split. Same fields and meaning as the
    shared-expense create request; omitted fields mean "owner pays, all active members
    share equally" when each occurrence is created."""

    paid_by_user_id: uuid.UUID | None = Field(None, description="Single payer (a group member).")
    payments: dict[str, StrictInt] | None = Field(
        None,
        max_length=MAX_SPLIT_ENTRIES,
        description="Map of member UUID to integer paise paid; must sum to amount_paise.",
    )
    participant_user_ids: list[uuid.UUID] | None = Field(
        None,
        max_length=MAX_SPLIT_ENTRIES,
        description="Members who share the expense. Defaults to all active members at creation time.",
    )
    split_mode: SplitMode = Field(SplitMode.EQUAL, description="equal, exact, percentage or parts.")
    split_weights: dict[str, Any] | None = Field(
        None,
        max_length=MAX_SPLIT_ENTRIES,
        description="Per-member weights for exact (integer paise), percentage or parts modes.",
    )


class RecurringRuleCreate(_StrictSchema):
    """Payload for creating a recurring expense rule."""

    frequency: Frequency = Field(..., description="daily, weekly, monthly or yearly.")
    start_date: date = Field(..., description="First occurrence (Asia/Kolkata); today or later.")
    end_date: date | None = Field(None, description="Last possible occurrence date (inclusive).")
    amount_paise: int = Field(..., description="Amount of each expense in integer paise (> 0).")
    category_id: uuid.UUID
    description: str = Field(..., min_length=1, max_length=255)
    notes: str | None = Field(None, max_length=1000)
    merchant: str | None = Field(None, max_length=255)
    payment_mode: str | None = Field(None, max_length=50)
    group_id: uuid.UUID | None = Field(None, description="Set for a group rule; omit for a personal rule.")
    split: RecurringSplit | None = Field(None, description="Group rules only.")

    @field_validator("amount_paise", mode="before")
    @classmethod
    def _amount_check(cls, v: Any) -> int:
        return _amount(v)

    @field_validator("description")
    @classmethod
    def _description_check(cls, v: str) -> str:
        return _clean_description(v)

    @model_validator(mode="after")
    def _check_dates_and_split(self) -> "RecurringRuleCreate":
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        if self.split is not None and self.group_id is None:
            raise ValueError("split is only allowed for a group rule (group_id).")
        return self


class RecurringRuleUpdate(_StrictSchema):
    """Partial edit. Changes apply to future occurrences only; expenses already created are
    never modified. frequency, start_date and group_id cannot be changed (cancel and create
    a new rule instead). Send ``null`` for end_date/notes/merchant/payment_mode to clear them."""

    amount_paise: int | None = None
    category_id: uuid.UUID | None = None
    description: str | None = Field(None, min_length=1, max_length=255)
    notes: str | None = Field(None, max_length=1000)
    merchant: str | None = Field(None, max_length=255)
    payment_mode: str | None = Field(None, max_length=50)
    end_date: date | None = None
    split: RecurringSplit | None = None

    @field_validator("amount_paise", mode="before")
    @classmethod
    def _amount_check(cls, v: Any) -> int | None:
        return None if v is None else _amount(v)

    @field_validator("description")
    @classmethod
    def _description_check(cls, v: str | None) -> str | None:
        return None if v is None else _clean_description(v)

    @model_validator(mode="after")
    def _check_fields(self) -> "RecurringRuleUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in ("amount_paise", "category_id", "description", "split"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class RecurringRuleResponse(BaseSchema):
    id: uuid.UUID
    group_id: uuid.UUID | None = None
    frequency: Frequency
    start_date: date
    end_date: date | None = None
    next_run_date: date | None = Field(
        None, description="Next occurrence that will be created; null when none remains."
    )
    status: RuleStatus
    amount_paise: int
    category_id: uuid.UUID
    description: str
    notes: str | None = None
    merchant: str | None = None
    payment_mode: str | None = None
    split: RecurringSplit | None = None
    created_at: datetime
    updated_at: datetime
    paused_at: datetime | None = None
    cancelled_at: datetime | None = None


class RecurringRuleDataResponse(BaseSchema):
    data: RecurringRuleResponse


class RecurringListMeta(BaseSchema):
    total: int
    limit: int
    offset: int


class RecurringRuleListResponse(BaseSchema):
    data: list[RecurringRuleResponse]
    meta: RecurringListMeta


class RecurringOccurrenceResponse(BaseSchema):
    id: uuid.UUID
    occurrence_date: date
    status: OccurrenceStatus
    expense_id: uuid.UUID | None = Field(
        None, description="The created expense; null if skipped or the expense was later hard-deleted."
    )
    skip_reason: str | None = Field(None, description="Error code explaining why the date was skipped.")
    created_at: datetime


class RecurringOccurrenceListResponse(BaseSchema):
    data: list[RecurringOccurrenceResponse]
    meta: RecurringListMeta
