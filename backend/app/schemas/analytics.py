"""Analytics schemas (US-12 / T-42).

Plain snake_case models (like the settlement schemas) so every money field is
named ``*_paise`` on the wire. All money is integer paise.

Definitions (ledger.md, PRODUCT.md section 05):
- share_paise: the user's spending = their share of every expense
  (a personal expense counts in full; a shared expense counts their share row).
- cash_paid_paise: what the user actually paid (a personal expense in full;
  for a shared expense, their payment rows).
- Settlements are never spending or income, and soft-deleted expenses are excluded.
- Dates are calendar days in Asia/Kolkata; weeks run Monday to Sunday.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Granularity = Literal["day", "week", "month"]

TIMEZONE = "Asia/Kolkata"


class AnalyticsBaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AnalyticsRange(AnalyticsBaseSchema):
    from_date: date = Field(..., description="First day of the range (inclusive), Asia/Kolkata.")
    to_date: date = Field(..., description="Last day of the range (inclusive), Asia/Kolkata.")
    timezone: str = Field(default=TIMEZONE, description="Time zone the dates are in.")
    group_id: uuid.UUID | None = Field(
        default=None, description="When set, only expenses of this group (personal expenses excluded)."
    )


class AnalyticsSummaryResponse(AnalyticsRange):
    share_paise: int = Field(..., description="Your spending in the range: your share of every expense.")
    cash_paid_paise: int = Field(..., description="What you actually paid in the range.")
    expense_count: int = Field(..., description="Expenses in the range you have a share in or paid for.")
    owed_to_you_paise: int = Field(
        ...,
        description="Current total others owe you across your groups (ledger engine; not limited to the range).",
    )
    you_owe_paise: int = Field(
        ...,
        description="Current total you owe across your groups (ledger engine; not limited to the range).",
    )


class TrendBucket(AnalyticsBaseSchema):
    bucket_start: date = Field(..., description="Calendar start of the bucket (a Monday for weeks, the 1st for months).")
    bucket_end: date = Field(..., description="Calendar end of the bucket (inclusive).")
    share_paise: int
    cash_paid_paise: int
    cumulative_share_paise: int = Field(..., description="Running total of share_paise from the start of the range.")
    cumulative_cash_paid_paise: int = Field(..., description="Running total of cash_paid_paise from the start of the range.")


class AnalyticsTrendsResponse(AnalyticsRange):
    granularity: Granularity
    buckets: list[TrendBucket] = Field(..., description="Every bucket in the range, empty ones as 0, oldest first.")
    total_share_paise: int
    total_cash_paid_paise: int


class CategoryBreakdownItem(AnalyticsBaseSchema):
    category_id: uuid.UUID
    category_name: str
    share_paise: int
    cash_paid_paise: int
    expense_count: int


class AnalyticsCategoriesResponse(AnalyticsRange):
    categories: list[CategoryBreakdownItem] = Field(
        ..., description="Sorted by share_paise, then cash_paid_paise (both descending), then name."
    )
    total_share_paise: int
    total_cash_paid_paise: int
