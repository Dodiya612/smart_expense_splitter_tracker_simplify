"""Analytics endpoints (US-12 / T-42): your share versus cash paid, over time and by category.

All figures are for the signed-in user only (derived from the access token, never from
a client-supplied user id). Money is integer paise; dates are Asia/Kolkata calendar days.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsCategoriesResponse,
    AnalyticsSummaryResponse,
    AnalyticsTrendsResponse,
    Granularity,
)
from app.services import analytics_service

router = APIRouter()

FromDate = Annotated[
    date | None,
    Query(alias="from", description="First day (YYYY-MM-DD, inclusive). Default: 1st of the month of 'to'."),
]
ToDate = Annotated[
    date | None,
    Query(alias="to", description="Last day (YYYY-MM-DD, inclusive). Default: today in Asia/Kolkata."),
]
GroupFilter = Annotated[
    uuid.UUID | None,
    Query(description="Only this group's expenses (current or past members only; others get 404)."),
]

RANGE_ERRORS: dict[int | str, dict[str, str]] = {
    400: {"description": "INVALID_RANGE ('from' after 'to') or RANGE_TOO_LARGE (over 731 days)."},
    401: {"description": "Not signed in."},
    404: {"description": "GROUP_NOT_FOUND: the group does not exist or you were never a member."},
}


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Spending summary for a date range",
    description="Your share and cash paid in the range, how many expenses, and what you are owed / owe now.",
    responses=RANGE_ERRORS,
)
async def get_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: FromDate = None,
    to_date: ToDate = None,
    group_id: GroupFilter = None,
) -> AnalyticsSummaryResponse:
    return await analytics_service.get_summary(db, current_user, from_date, to_date, group_id)


@router.get(
    "/trends",
    response_model=AnalyticsTrendsResponse,
    status_code=status.HTTP_200_OK,
    summary="Spending over time",
    description="Share and cash paid per day, week (Monday–Sunday) or month, with running totals. "
    "Empty buckets are included as 0.",
    responses=RANGE_ERRORS,
)
async def get_trends(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    granularity: Annotated[Granularity, Query(description="day, week or month.")] = "day",
    from_date: FromDate = None,
    to_date: ToDate = None,
    group_id: GroupFilter = None,
) -> AnalyticsTrendsResponse:
    return await analytics_service.get_trends(db, current_user, granularity, from_date, to_date, group_id)


@router.get(
    "/categories",
    response_model=AnalyticsCategoriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Spending by category",
    description="Share and cash paid per category in the range, largest share first.",
    responses=RANGE_ERRORS,
)
async def get_categories(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: FromDate = None,
    to_date: ToDate = None,
    group_id: GroupFilter = None,
) -> AnalyticsCategoriesResponse:
    return await analytics_service.get_categories(db, current_user, from_date, to_date, group_id)
