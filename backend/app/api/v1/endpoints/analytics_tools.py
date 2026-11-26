"""Analytics query‑tool endpoints (US‑24 / T‑52).

These lightweight endpoints provide pre‑configured analytics shortcuts for the AI
assistant. They are thin wrappers around the existing analytics service functions
(`get_summary`, `get_trends`, `get_categories`). Each endpoint returns the same
response models as the regular analytics API but with fixed date ranges or
granularity to simplify the assistant’s queries.

Endpoints
---------
* ``/daily-spending`` – summary for *today*.
* ``/weekly-spending`` – summary for the ISO week (Monday‑Sunday) containing
  *today*.
* ``/monthly-spending`` – summary for the calendar month containing *today*.
* ``/group-spending`` – summary for a specific group (optional date range).
* ``/total-spending`` – summary for all time, capped at the two years ending today.
* ``/daily-trends`` – trend buckets for ``day`` granularity over the last 30
  days.
* ``/weekly-trends`` – trend buckets for ``week`` granularity over the last 12
  weeks.
* ``/monthly-trends`` – trend buckets for ``month`` granularity over the last
  12 months.

All endpoints require an authenticated user (``get_current_user``) and a
database session (``get_db``). They deliberately avoid raw SQL – all data is
retrieved via the existing service layer.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    AnalyticsTrendsResponse,
)
from app.services import analytics_service
from app.services.date_ranges import (
    all_time_range,
    daily_trend_window,
    month_range,
    monthly_trend_window,
    today_in_kolkata,
    week_range,
    weekly_trend_window,
)

router = APIRouter()

# Date ranges come from app/services/date_ranges.py, the resolver shared with the
# assistant (T-57); "today" is the calendar day in Asia/Kolkata.

# ---------------------------------------------------------------------------
# Summary shortcuts
# ---------------------------------------------------------------------------

@router.get(
    "/daily-spending",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Daily spending summary (today)",
)
async def daily_spending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    today = today_in_kolkata()
    return await analytics_service.get_summary(db, current_user, today, today, None)


@router.get(
    "/weekly-spending",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Weekly spending summary (current ISO week)",
)
async def weekly_spending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    start, end = week_range(today_in_kolkata())
    return await analytics_service.get_summary(db, current_user, start, end, None)


@router.get(
    "/monthly-spending",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Monthly spending summary (current calendar month)",
)
async def monthly_spending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    start, end = month_range(today_in_kolkata())
    return await analytics_service.get_summary(db, current_user, start, end, None)


@router.get(
    "/group-spending",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Spending summary for a specific group",
)
async def group_spending(
    group_id: uuid.UUID = Query(..., description="Group UUID"),
    from_date: date | None = Query(None, alias="from", description="Start date (inclusive)"),
    to_date: date | None = Query(None, alias="to", description="End date (inclusive)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    return await analytics_service.get_summary(db, current_user, from_date, to_date, group_id)


@router.get(
    "/total-spending",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Overall spending summary (the last two years)",
    description="All time, capped at the longest range the analytics service accepts: the "
    "731 days ending today (Asia/Kolkata).",
)
async def total_spending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    start, end = all_time_range(today_in_kolkata())
    return await analytics_service.get_summary(db, current_user, start, end, None)

# ---------------------------------------------------------------------------
# Trend shortcuts – fixed granularity and sensible default ranges.
# ---------------------------------------------------------------------------

@router.get(
    "/daily-trends",
    response_model=AnalyticsTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Daily trends for the past 30 days",
)
async def daily_trends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsTrendsResponse:
    start, end = daily_trend_window(today_in_kolkata())
    return await analytics_service.get_trends(
        db, current_user, "day", start, end, None
    )


@router.get(
    "/weekly-trends",
    response_model=AnalyticsTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Weekly trends for the past 12 weeks",
)
async def weekly_trends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsTrendsResponse:
    start, end = weekly_trend_window(today_in_kolkata())
    return await analytics_service.get_trends(
        db, current_user, "week", start, end, None
    )


@router.get(
    "/monthly-trends",
    response_model=AnalyticsTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Monthly trends for the past 12 months",
)
async def monthly_trends(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsTrendsResponse:
    start, end = monthly_trend_window(today_in_kolkata())
    return await analytics_service.get_trends(
        db, current_user, "month", start, end, None
    )

# The router is automatically included via ``backend/app/api/v1/api.py`` which
# imports all endpoint modules.
