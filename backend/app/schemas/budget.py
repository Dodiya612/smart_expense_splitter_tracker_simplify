"""Budget schemas (US-25 / T-48).

Money is integer paise (``limit_paise``); floats and booleans are rejected. Periods are
calendar weeks (Monday to Sunday) or calendar months in Asia/Kolkata. Unknown fields are
rejected (422), so ownership fields such as ``user_id`` can never be supplied.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from app.schemas.common import BaseSchema, to_camel
from app.schemas.expense import validate_paise_amount

BudgetPeriod = Literal["weekly", "monthly"]
BudgetStatus = Literal["under", "warning", "exceeded"]

MAX_LIMIT_PAISE = 9_223_372_036_854_775_807  # BIGINT upper bound, as for settlements


class _StrictSchema(BaseSchema):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


def _limit(value: Any) -> int:
    paise = validate_paise_amount(value)
    if paise > MAX_LIMIT_PAISE:
        raise ValueError(f"Limit must be at most {MAX_LIMIT_PAISE} paise.")
    return paise


class BudgetCreate(_StrictSchema):
    """Payload for creating a budget. Omit ``category_id`` for an overall budget."""

    period: BudgetPeriod = Field(..., description="weekly (Monday to Sunday) or monthly (calendar month).")
    limit_paise: int = Field(..., description="Spending limit per period in integer paise (> 0).")
    category_id: uuid.UUID | None = Field(
        None, description="Limit spending in one category; omit for an overall budget."
    )

    @field_validator("limit_paise", mode="before")
    @classmethod
    def _limit_check(cls, v: Any) -> int:
        return _limit(v)


class BudgetUpdate(_StrictSchema):
    """Change the limit. The period and category cannot be changed (delete the budget and
    create a new one instead), because alerts already sent belong to the old definition."""

    limit_paise: int = Field(..., description="New spending limit per period in integer paise (> 0).")

    @field_validator("limit_paise", mode="before")
    @classmethod
    def _limit_check(cls, v: Any) -> int:
        return _limit(v)


class BudgetProgress(BaseSchema):
    """Spending against the limit in the current period (Asia/Kolkata).

    ``spent_paise`` is the user's share of every live expense dated in the period (a
    personal expense counts in full, a shared expense counts the user's share). Cash paid
    and settlements never count.
    """

    period_start: date
    period_end: date
    spent_paise: int
    remaining_paise: int = Field(..., description="limit - spent; negative when over the limit.")
    over_by_paise: int = Field(..., description="How far spending is over the limit; 0 when not over.")
    percent_used: int = Field(..., description="floor(spent * 100 / limit).")
    status: BudgetStatus = Field(..., description="under (< 80%), warning (80% to < 100%) or exceeded (>= 100%).")


class BudgetResponse(BaseSchema):
    id: uuid.UUID
    period: BudgetPeriod
    category_id: uuid.UUID | None = None
    limit_paise: int
    created_at: datetime
    updated_at: datetime
    progress: BudgetProgress


class BudgetDataResponse(BaseSchema):
    data: BudgetResponse


class BudgetListMeta(BaseSchema):
    total: int
    limit: int
    offset: int


class BudgetListResponse(BaseSchema):
    data: list[BudgetResponse]
    meta: BudgetListMeta
