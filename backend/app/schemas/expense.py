import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.schemas.common import BaseSchema


def validate_paise_amount(val: Any) -> int:
    """Validate that the amount is a strictly positive integer number of paise."""
    if isinstance(val, bool):
        raise ValueError("Amount cannot be a boolean.")  # noqa: TRY004
    if isinstance(val, float):
        raise ValueError("Floating-point money values are not allowed. Provide integer paise.")  # noqa: TRY004
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


class ExpenseCreate(BaseSchema):
    """Payload for creating a personal expense."""

    amount_minor: int | None = Field(
        None,
        description="Amount in whole integer paise (strictly > 0).",
    )
    amount_paise: int | None = Field(
        None,
        description="Alias for amount_minor in whole integer paise.",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Brief description of the expense.",
    )
    category_id: uuid.UUID = Field(
        ...,
        description="UUID of the selected category.",
    )
    expense_date: date | None = Field(
        None,
        description="Date of the expense (YYYY-MM-DD). Defaults to current date.",
    )
    occurred_on: date | None = Field(
        None,
        description="Alias for expense_date matching API contracts.",
    )
    notes: str | None = Field(
        None,
        max_length=1000,
        description="Optional detailed notes.",
    )
    merchant: str | None = Field(
        None,
        max_length=255,
        description="Optional merchant or vendor name.",
    )
    payment_mode: str | None = Field(
        None,
        max_length=50,
        description="Optional payment mode, e.g. cash, upi, card, net_banking.",
    )
    receipt_id: uuid.UUID | None = Field(
        None,
        description="Optional reference ID to an uploaded receipt.",
    )

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
        raw_amount = values.get("amount_minor")
        if raw_amount is None:
            raw_amount = values.get("amount_paise")
            if raw_amount is None:
                # Check camelCase
                raw_amount = values.get("amountMinor")
                if raw_amount is None:
                    raw_amount = values.get("amountPaise")

        if raw_amount is None:
            raise ValueError("Amount is required (provide amount_minor or amount_paise).")

        validated_amount = validate_paise_amount(raw_amount)
        values["amount_minor"] = validated_amount
        values["amount_paise"] = validated_amount

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


class ExpenseUpdate(BaseSchema):
    """Payload for updating an existing personal expense (supports partial updates)."""

    version: int | None = Field(
        None,
        description="Current version number for optimistic concurrency checking.",
    )
    amount_minor: int | None = Field(
        None,
        description="Updated amount in whole integer paise (strictly > 0).",
    )
    amount_paise: int | None = Field(
        None,
        description="Alias for updated amount_minor in whole integer paise.",
    )
    description: str | None = Field(
        None,
        min_length=1,
        max_length=255,
        description="Updated brief description of the expense.",
    )
    category_id: uuid.UUID | None = Field(
        None,
        description="Updated UUID of the category.",
    )
    expense_date: date | None = Field(
        None,
        description="Updated date of the expense (YYYY-MM-DD).",
    )
    occurred_on: date | None = Field(
        None,
        description="Alias for expense_date matching API contracts.",
    )
    notes: str | None = Field(
        None,
        max_length=1000,
        description="Updated detailed notes.",
    )
    merchant: str | None = Field(
        None,
        max_length=255,
        description="Updated merchant or vendor name.",
    )
    payment_mode: str | None = Field(
        None,
        max_length=50,
        description="Updated payment mode, e.g. cash, upi, card, net_banking.",
    )
    receipt_id: uuid.UUID | None = Field(
        None,
        description="Updated reference ID to an uploaded receipt.",
    )

    @field_validator("description")
    @classmethod
    def clean_description(cls, v: str | None) -> str | None:
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
        raw_amount = values.get("amount_minor")
        if raw_amount is None:
            raw_amount = values.get("amount_paise")
            if raw_amount is None:
                raw_amount = values.get("amountMinor")
                if raw_amount is None:
                    raw_amount = values.get("amountPaise")

        if raw_amount is not None:
            validated_amount = validate_paise_amount(raw_amount)
            values["amount_minor"] = validated_amount
            values["amount_paise"] = validated_amount

        # Reconcile date
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


class ExpenseResponse(BaseSchema):
    """Schema representing an expense returned to the client."""

    id: uuid.UUID
    user_id: uuid.UUID
    category_id: uuid.UUID
    amount_minor: int
    amount_paise: int
    description: str
    expense_date: date
    occurred_on: date
    notes: str | None = None
    merchant: str | None = None
    payment_mode: str | None = None
    receipt_id: uuid.UUID | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def set_computed_aliases(cls, values: Any) -> Any:
        if hasattr(values, "amount_minor"):
            # SQLAlchemy model or object
            amount = values.amount_minor
            exp_date = values.expense_date
            data = {
                "id": values.id,
                "user_id": values.user_id,
                "category_id": values.category_id,
                "amount_minor": amount,
                "amount_paise": amount,
                "description": values.description,
                "expense_date": exp_date,
                "occurred_on": exp_date,
                "notes": getattr(values, "notes", None),
                "merchant": getattr(values, "merchant", None),
                "payment_mode": getattr(values, "payment_mode", None),
                "receipt_id": getattr(values, "receipt_id", None),
                "version": getattr(values, "version", 1),
                "created_at": values.created_at,
                "updated_at": values.updated_at,
                "deleted_at": getattr(values, "deleted_at", None),
            }
            return data
        elif isinstance(values, dict):
            if "amount_minor" in values and "amount_paise" not in values:
                values["amount_paise"] = values["amount_minor"]
            elif "amount_paise" in values and "amount_minor" not in values:
                values["amount_minor"] = values["amount_paise"]

            if "expense_date" in values and "occurred_on" not in values:
                values["occurred_on"] = values["expense_date"]
            elif "occurred_on" in values and "expense_date" not in values:
                values["expense_date"] = values["occurred_on"]
        return values


class ExpenseDataResponse(BaseSchema):
    """Standard envelope for a single expense: { "data": { ... } }."""

    data: ExpenseResponse


class ExpenseListMeta(BaseSchema):
    """Metadata for paginated expense lists."""

    total: int
    limit: int
    offset: int
    next_cursor: str | None = None


class ExpenseListResponse(BaseSchema):
    """Standard envelope for a list of expenses: { "data": [ ... ], "meta": { ... } }."""

    data: list[ExpenseResponse]
    meta: ExpenseListMeta


class ExpenseDeleteResponse(BaseSchema):
    """Response returned upon soft deleting an expense."""

    data: dict[str, Any]
    message: str = "Expense deleted successfully."


class ExpenseRestoreResponse(BaseSchema):
    """Response returned upon restoring a soft-deleted expense."""

    data: ExpenseResponse
    message: str = "Expense restored successfully."


class ExpenseTotalData(BaseSchema):
    """Aggregated spending total for active expenses."""

    total_paise: int
    currency: str = "INR"
    count: int


class ExpenseTotalResponse(BaseSchema):
    """Envelope for spending total response."""

    data: ExpenseTotalData
