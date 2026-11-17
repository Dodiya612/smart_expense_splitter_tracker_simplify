from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator, model_validator

from app.schemas.common import BaseSchema
from app.schemas.ledger import SplitMode


def validate_paise_amount(val: Any) -> int:
    """Validate that the amount is a strictly positive integer number of paise."""
    if isinstance(val, bool):
        raise ValueError("Amount cannot be a boolean.")
    if isinstance(val, float):
        raise ValueError("Floating-point money values are not allowed. Provide integer paise.")
    if not isinstance(val, int):
        try:
            val = int(val)
        except (ValueError, TypeError):
            raise ValueError("Amount must be a valid integer number of paise.") from None
    if val <= 0:
        raise ValueError("Expense amount must be strictly greater than zero.")
    return val


def validate_expense_date_not_future(d: date | None) -> date | None:
    """Ensure expense date is not later than tomorrow in UTC."""
    if d is None:
        return d
    today_utc = datetime.now(UTC).date()
    max_allowed = today_utc + timedelta(days=1)
    if d > max_allowed:
        raise ValueError(f"Expense date cannot be later than tomorrow ({max_allowed}).")
    return d


class ExpensePaymentItem(BaseSchema):
    """Payment record indicating who paid how much in paise."""

    user_id: uuid.UUID = Field(..., description="UUID of the payer.")
    amount_paise: int = Field(..., gt=0, description="Amount paid in integer paise (> 0).")


class ExpenseShareItem(BaseSchema):
    """Share record indicating who owes how much in paise."""

    user_id: uuid.UUID = Field(..., description="UUID of the participant.")
    amount_paise: int = Field(..., ge=0, description="Share amount in integer paise (>= 0).")
    rule: str = Field(default="equal", description="Split rule used (e.g. equal, exact, percentage, parts).")
    rule_value: Optional[float] = Field(None, description="Optional weight/value associated with the split rule.")


class SharedExpenseCreateRequest(BaseSchema):
    """Payload for creating a shared expense within a group."""

    amount_minor: Optional[int] = Field(None, description="Amount in integer paise (> 0).")
    amount_paise: Optional[int] = Field(None, description="Alias for amount_minor.")
    description: str = Field(..., min_length=1, max_length=255, description="Brief description of the expense.")
    category_id: uuid.UUID = Field(..., description="UUID of the category.")
    expense_date: Optional[date] = Field(None, description="Date of the expense (YYYY-MM-DD).")
    occurred_on: Optional[date] = Field(None, description="Alias for expense_date.")
    paid_by_user_id: Optional[uuid.UUID] = Field(None, description="Single payer UUID if single payer.")
    payments: Optional[Dict[str, int]] = Field(
        None,
        description="Map of user UUID to paise paid (for multiple payers or explicit payments).",
    )
    participant_user_ids: Optional[List[uuid.UUID]] = Field(
        None,
        description="Explicit list of participant UUIDs. Defaults to all active group members.",
    )
    split_mode: SplitMode = Field(
        default=SplitMode.EQUAL,
        description="Split calculation strategy (equal, exact, percentage, parts).",
    )
    split_weights: Optional[Dict[str, Any]] = Field(
        None,
        description="Weights for exact, percentage, or parts split modes mapped by user UUID string.",
    )
    notes: Optional[str] = Field(None, max_length=1000, description="Optional notes.")
    merchant: Optional[str] = Field(None, max_length=255, description="Optional merchant name.")
    payment_mode: Optional[str] = Field(None, max_length=50, description="Optional payment mode.")

    @field_validator("description")
    @classmethod
    def clean_description(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Description cannot be empty or only whitespace.")
        return s

    @model_validator(mode="before")
    @classmethod
    def reconcile_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # Reconcile amount_minor vs amount_paise
        raw_amount = values.get("amount_paise")
        if raw_amount is None:
            raw_amount = values.get("amount_minor")
            if raw_amount is None:
                raw_amount = values.get("amountPaise")
                if raw_amount is None:
                    raw_amount = values.get("amountMinor")

        if raw_amount is None:
            raise ValueError("Amount is required (provide amount_paise or amount_minor).")

        validated_amount = validate_paise_amount(raw_amount)
        values["amount_paise"] = validated_amount
        values["amount_minor"] = validated_amount

        # Reconcile expense_date vs occurred_on
        raw_date = values.get("expense_date")
        if raw_date is None:
            raw_date = values.get("occurred_on")
            if raw_date is None:
                raw_date = values.get("expenseDate")
                if raw_date is None:
                    raw_date = values.get("occurredOn")

        if raw_date is None:
            raw_date = datetime.now(UTC).date()
        elif isinstance(raw_date, str):
            try:
                raw_date = date.fromisoformat(raw_date)
            except ValueError:
                raise ValueError("Invalid date format. Expected YYYY-MM-DD.")

        validated_date = validate_expense_date_not_future(raw_date)
        values["expense_date"] = validated_date
        values["occurred_on"] = validated_date

        return values


class SharedExpenseResponse(BaseSchema):
    """Response returned when a shared expense is created or fetched."""

    id: uuid.UUID
    group_id: uuid.UUID
    user_id: uuid.UUID
    category_id: uuid.UUID
    amount_paise: int
    amount_minor: int
    description: str
    expense_date: date
    notes: Optional[str] = None
    merchant: Optional[str] = None
    payment_mode: Optional[str] = None
    split_mode: str
    payments: List[ExpensePaymentItem]
    shares: List[ExpenseShareItem]
    version: int = 1
    created_at: datetime
    updated_at: datetime


class SharedExpenseUpdateRequest(BaseSchema):
    """Payload for updating an existing shared expense within a group."""

    version: Optional[int] = Field(None, description="Current version number for optimistic concurrency.")
    amount_minor: Optional[int] = Field(None, description="Updated amount in whole integer paise (> 0).")
    amount_paise: Optional[int] = Field(None, description="Alias for amount_minor.")
    description: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated brief description.")
    category_id: Optional[uuid.UUID] = Field(None, description="Updated UUID of the category.")
    expense_date: Optional[date] = Field(None, description="Updated date of the expense (YYYY-MM-DD).")
    occurred_on: Optional[date] = Field(None, description="Alias for expense_date.")
    paid_by_user_id: Optional[uuid.UUID] = Field(None, description="Single payer UUID if single payer.")
    payments: Optional[Dict[str, int]] = Field(
        None,
        description="Map of user UUID to paise paid (for multiple payers or explicit payments).",
    )
    participant_user_ids: Optional[List[uuid.UUID]] = Field(
        None,
        description="Explicit list of participant UUIDs.",
    )
    split_mode: Optional[SplitMode] = Field(
        None,
        description="Split calculation strategy (equal, exact, percentage, parts).",
    )
    split_weights: Optional[Dict[str, Any]] = Field(
        None,
        description="Weights for exact, percentage, or parts split modes mapped by user UUID string.",
    )
    notes: Optional[str] = Field(None, max_length=1000, description="Optional updated notes.")
    merchant: Optional[str] = Field(None, max_length=255, description="Optional updated merchant name.")
    payment_mode: Optional[str] = Field(None, max_length=50, description="Optional updated payment mode.")

    @field_validator("description")
    @classmethod
    def clean_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = v.strip()
        if not s:
            raise ValueError("Description cannot be empty or only whitespace.")
        return s

    @model_validator(mode="before")
    @classmethod
    def reconcile_update_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # Reconcile amount
        raw_amount = values.get("amount_paise")
        if raw_amount is None:
            raw_amount = values.get("amount_minor")
            if raw_amount is None:
                raw_amount = values.get("amountPaise")
                if raw_amount is None:
                    raw_amount = values.get("amountMinor")

        if raw_amount is not None:
            validated_amount = validate_paise_amount(raw_amount)
            values["amount_paise"] = validated_amount
            values["amount_minor"] = validated_amount

        # Reconcile expense_date
        raw_date = values.get("expense_date")
        if raw_date is None:
            raw_date = values.get("occurred_on")
            if raw_date is None:
                raw_date = values.get("expenseDate")
                if raw_date is None:
                    raw_date = values.get("occurredOn")

        if raw_date is not None:
            if isinstance(raw_date, str):
                try:
                    raw_date = date.fromisoformat(raw_date)
                except ValueError:
                    raise ValueError("Invalid date format. Expected YYYY-MM-DD.")
            validated_date = validate_expense_date_not_future(raw_date)
            values["expense_date"] = validated_date
            values["occurred_on"] = validated_date

        return values


class SharedExpenseDeleteResponse(BaseSchema):
    """Response returned upon successful soft deletion of a shared expense."""

    message: str = Field(default="Shared expense deleted successfully.")
    expense_id: uuid.UUID
    group_id: uuid.UUID
    deleted: bool = True
    version: int
    net_positions: Dict[str, int]
    suggested_transfers: List[Dict[str, Any]]


class GroupHistoryItemResponse(BaseSchema):
    """Audit log entry for a group transaction history record."""

    id: uuid.UUID
    group_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    actor_id: Optional[uuid.UUID] = None
    before_after: Optional[Dict[str, Any]] = None
    created_at: datetime

