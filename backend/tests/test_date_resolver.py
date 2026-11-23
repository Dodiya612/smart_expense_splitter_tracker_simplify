import pytest
from datetime import date, timedelta
from fastapi import HTTPException

from app.services.analytics_service import resolve_range, bucket_start, bucket_end, iter_bucket_starts

# Helper to get a fixed "today" date for reproducible tests
FIXED_TODAY = date(2024, 4, 15)  # 15th April 2024 (Monday)

def test_resolve_range_defaults():
    start, end = resolve_range(None, None, FIXED_TODAY)
    # Default start = first of month of END (April 1st)
    assert start == date(2024, 4, 1)
    assert end == FIXED_TODAY

def test_resolve_range_custom():
    custom_from = date(2024, 3, 10)
    custom_to = date(2024, 3, 20)
    start, end = resolve_range(custom_from, custom_to, FIXED_TODAY)
    assert start == custom_from
    assert end == custom_to

def test_resolve_range_invalid_order():
    with pytest.raises(HTTPException) as exc:
        resolve_range(date(2024, 5, 1), date(2024, 4, 1), FIXED_TODAY)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "INVALID_RANGE"

def test_resolve_range_too_large():
    # Create a range longer than 731 days
    long_from = FIXED_TODAY - timedelta(days=800)
    with pytest.raises(HTTPException) as exc:
        resolve_range(long_from, FIXED_TODAY, FIXED_TODAY)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "RANGE_TOO_LARGE"

def test_bucket_start_day():
    d = date(2024, 4, 10)
    assert bucket_start(d, "day") == d

def test_bucket_start_week():
    # 2024-04-10 is Wednesday; Monday of same week is 2024-04-08
    d = date(2024, 4, 10)
    assert bucket_start(d, "week") == date(2024, 4, 8)

def test_bucket_start_month():
    d = date(2024, 4, 20)
    assert bucket_start(d, "month") == date(2024, 4, 1)

def test_bucket_end_day():
    d = date(2024, 4, 10)
    assert bucket_end(d, "day") == d

def test_bucket_end_week():
    start = date(2024, 4, 8)  # Monday
    assert bucket_end(start, "week") == date(2024, 4, 14)  # Sunday

def test_bucket_end_month():
    start = date(2024, 2, 1)
    # February 2024 has 29 days (leap year)
    assert bucket_end(start, "month") == date(2024, 2, 29)

def test_iter_bucket_starts_day():
    start = date(2024, 4, 1)
    end = date(2024, 4, 3)
    buckets = iter_bucket_starts(start, end, "day")
    assert buckets == [date(2024, 4, 1), date(2024, 4, 2), date(2024, 4, 3)]

def test_iter_bucket_starts_week():
    start = date(2024, 4, 3)  # Wednesday
    end = date(2024, 4, 20)
    buckets = iter_bucket_starts(start, end, "week")
    # Weeks start on Monday, so first bucket is 2024-04-01 (Monday of that week)
    assert buckets == [date(2024, 4, 1), date(2024, 4, 8), date(2024, 4, 15)]

def test_iter_bucket_starts_month():
    start = date(2024, 1, 15)
    end = date(2024, 3, 10)
    buckets = iter_bucket_starts(start, end, "month")
    assert buckets == [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)]
