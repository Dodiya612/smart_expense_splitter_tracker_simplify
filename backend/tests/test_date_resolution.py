"""Unit tests for deterministic DateResolver in Asia/Kolkata timezone (T-57 / US-24)."""

import calendar
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.ai.date_resolver import KOLKATA_TZ, DateResolver, ResolvedDateRange


def test_kolkata_timezone_configured():
    """Verify timezone is strictly Asia/Kolkata (IST)."""
    assert KOLKATA_TZ.key == "Asia/Kolkata"
    dt = DateResolver.get_current_ist_datetime()
    assert dt.tzinfo is not None
    assert dt.tzname() == "IST"


def test_today_resolution():
    """Verify 'today' resolves to the reference date."""
    ref = date(2026, 11, 22)
    resolved = DateResolver.resolve_relative_keyword("today", ref_date=ref)
    assert resolved.start_date == ref
    assert resolved.end_date == ref
    assert resolved.period_label == "today"


def test_yesterday_resolution():
    """Verify 'yesterday' resolves to ref_date - 1 day."""
    ref = date(2026, 11, 22)
    resolved = DateResolver.resolve_relative_keyword("yesterday", ref_date=ref)
    expected = date(2026, 11, 21)
    assert resolved.start_date == expected
    assert resolved.end_date == expected
    assert resolved.period_label == "yesterday"


def test_this_week_boundaries():
    """Verify 'this_week' starts on Monday and ends on Sunday."""
    # 2026-11-22 is Sunday (weekday 6)
    ref = date(2026, 11, 22)
    resolved = DateResolver.resolve_relative_keyword("this_week", ref_date=ref)
    assert resolved.start_date == date(2026, 11, 16)  # Monday
    assert resolved.end_date == date(2026, 11, 22)    # Sunday
    assert (resolved.end_date - resolved.start_date).days == 6


def test_last_week_boundaries():
    """Verify 'last_week' starts on previous Monday and ends on previous Sunday."""
    # 2026-11-22 is Sunday
    ref = date(2026, 11, 22)
    resolved = DateResolver.resolve_relative_keyword("last_week", ref_date=ref)
    assert resolved.start_date == date(2026, 11, 9)   # Monday of last week
    assert resolved.end_date == date(2026, 11, 15)    # Sunday of last week
    assert (resolved.end_date - resolved.start_date).days == 6


def test_this_month_boundaries():
    """Verify 'this_month' spans 1st to last day of current month."""
    ref = date(2026, 11, 22)
    resolved = DateResolver.resolve_relative_keyword("this_month", ref_date=ref)
    assert resolved.start_date == date(2026, 11, 1)
    assert resolved.end_date == date(2026, 11, 30)


def test_last_month_boundaries_standard():
    """Verify 'last_month' in November resolves to October 1 - October 31."""
    ref = date(2026, 11, 22)
    resolved = DateResolver.resolve_relative_keyword("last_month", ref_date=ref)
    assert resolved.start_date == date(2026, 10, 1)
    assert resolved.end_date == date(2026, 10, 31)


def test_last_month_boundaries_january_rollover():
    """Verify 'last_month' in January rolls back to December of previous year."""
    ref = date(2026, 1, 15)
    resolved = DateResolver.resolve_relative_keyword("last_month", ref_date=ref)
    assert resolved.start_date == date(2025, 12, 1)
    assert resolved.end_date == date(2025, 12, 31)


def test_this_year_and_last_year():
    """Verify year boundaries."""
    ref = date(2026, 11, 22)
    this_y = DateResolver.resolve_relative_keyword("this_year", ref_date=ref)
    assert this_y.start_date == date(2026, 1, 1)
    assert this_y.end_date == date(2026, 12, 31)

    last_y = DateResolver.resolve_relative_keyword("last_year", ref_date=ref)
    assert last_y.start_date == date(2025, 1, 1)
    assert last_y.end_date == date(2025, 12, 31)


def test_resolve_from_text():
    """Verify extraction of date phrases from user questions."""
    ref = date(2026, 11, 22)

    res1 = DateResolver.resolve_from_text("How much did I spend on food last week?", ref_date=ref)
    assert res1 is not None
    assert res1.start_date == date(2026, 11, 9)
    assert res1.end_date == date(2026, 11, 15)

    res2 = DateResolver.resolve_from_text("Total spending this month", ref_date=ref)
    assert res2 is not None
    assert res2.start_date == date(2026, 11, 1)
    assert res2.end_date == date(2026, 11, 30)

    res3 = DateResolver.resolve_from_text("Expenses yesterday", ref_date=ref)
    assert res3 is not None
    assert res3.start_date == date(2026, 11, 21)

    res4 = DateResolver.resolve_from_text("Spending in October 2026", ref_date=ref)
    assert res4 is not None
    assert res4.start_date == date(2026, 10, 1)
    assert res4.end_date == date(2026, 10, 31)


def test_all_time_fallback():
    """Verify that unspecified date ranges resolve safely to all_time."""
    resolved = DateResolver.resolve(query_text="How much did I spend on food in total?")
    assert resolved.start_date is None
    assert resolved.end_date is None
    assert resolved.period_label == "all time"
