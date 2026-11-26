"""The shared Asia/Kolkata date resolver (app/services/date_ranges.py; T-52 and T-57)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.services import date_ranges, settlement_service
from app.services.date_ranges import (
    MAX_RANGE_DAYS,
    PeriodError,
    PeriodSlots,
    cap_at_today,
    daily_trend_window,
    month_range,
    monthly_trend_window,
    period_slots_from_text,
    periods_from_text,
    resolve_period,
    week_range,
    weekly_trend_window,
)

TUESDAY = date(2026, 11, 24)


def resolve(**slots):
    p = resolve_period(PeriodSlots(**slots), TUESDAY)
    return p.start, p.end, p.label


def from_text(text: str, today: date = TUESDAY):
    p = resolve_period(period_slots_from_text(text), today)
    return p.start, p.end, p.label


# ---- relative keywords --------------------------------------------------------------------


def test_today_and_yesterday():
    assert resolve(date_range="today") == (TUESDAY, TUESDAY, "today")
    assert resolve(date_range="yesterday") == (date(2026, 11, 23), date(2026, 11, 23), "yesterday")


def test_weeks_run_monday_to_sunday_and_last_week_is_the_previous_monday_to_sunday():
    assert resolve(date_range="this_week") == (date(2026, 11, 23), date(2026, 11, 29), "this week")
    assert resolve(date_range="last_week") == (date(2026, 11, 16), date(2026, 11, 22), "last week")
    # On a Monday "last week" is the seven days that ended yesterday.
    p = resolve_period(PeriodSlots(date_range="last_week"), date(2026, 11, 23))
    assert (p.start, p.end) == (date(2026, 11, 16), date(2026, 11, 22))
    # On a Sunday it is still the week before, never the current one.
    p = resolve_period(PeriodSlots(date_range="last_week"), date(2026, 11, 29))
    assert (p.start, p.end) == (date(2026, 11, 16), date(2026, 11, 22))


def test_months_and_years_including_the_january_rollover():
    assert resolve(date_range="this_month") == (date(2026, 11, 1), date(2026, 11, 30), "this month")
    assert resolve(date_range="last_month") == (date(2026, 10, 1), date(2026, 10, 31), "last month")
    p = resolve_period(PeriodSlots(date_range="last_month"), date(2027, 1, 1))
    assert (p.start, p.end) == (date(2026, 12, 1), date(2026, 12, 31))
    p = resolve_period(PeriodSlots(date_range="last_month"), date(2028, 3, 31))
    assert (p.start, p.end) == (date(2028, 2, 1), date(2028, 2, 29))  # leap year
    assert resolve(date_range="this_year") == (date(2026, 1, 1), date(2026, 12, 31), "this year")
    assert resolve(date_range="last_year") == (date(2025, 1, 1), date(2025, 12, 31), "last year")


def test_all_time_is_capped_at_the_longest_analytics_range_and_says_so():
    start, end, label = resolve(date_range="all_time")
    assert end == TUESDAY and (end - start).days + 1 == MAX_RANGE_DAYS
    assert label == "in the last 2 years"


def test_no_period_named_gives_the_analytics_default():
    assert resolve() == (date(2026, 11, 1), TUESDAY, "this month so far")


# ---- last N days, named months ------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 7, 30, 90, MAX_RANGE_DAYS])
def test_last_n_days_is_exactly_n_days_including_today(n):
    start, end, _ = resolve(last_days=n)
    assert end == TUESDAY and (end - start).days + 1 == n


def test_last_n_days_outside_the_limits_is_rejected():
    for n in (0, -3, MAX_RANGE_DAYS + 1):
        with pytest.raises(ValidationError):
            PeriodSlots(last_days=n)
    with pytest.raises(PeriodError):
        period_slots_from_text("How much did I spend in the last 800 days?")


def test_a_month_without_a_year_is_never_in_the_future():
    assert from_text("How much did I spend in October?") == (
        date(2026, 10, 1), date(2026, 10, 31), "in October 2026"
    )
    assert from_text("How much did I spend in November?") == (
        date(2026, 11, 1), date(2026, 11, 30), "in November 2026"
    )
    assert from_text("How much did I spend in December?") == (
        date(2025, 12, 1), date(2025, 12, 31), "in December 2025"
    )
    assert from_text("What did I spend in Jan?", date(2026, 1, 5))[0] == date(2026, 1, 1)


def test_a_named_month_with_a_future_year_is_reported():
    with pytest.raises(PeriodError):
        resolve_period(period_slots_from_text("Spending in March 2027"), TUESDAY)
    assert from_text("Spending in March 2026")[:2] == (date(2026, 3, 1), date(2026, 3, 31))


def test_may_i_is_not_the_month_may():
    assert period_slots_from_text("May I see my total spending?") == PeriodSlots()
    assert period_slots_from_text("May I know my spending this month?") == PeriodSlots(date_range="this_month")
    assert period_slots_from_text("How much did I spend in May?") == PeriodSlots(month="may")
    assert period_slots_from_text("Spending for May 2026") == PeriodSlots(month="may", year=2026)


# ---- reading periods from questions -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "slots"),
    [
        ("How much did I spend on food last week?", PeriodSlots(date_range="last_week")),
        ("Total spending this month", PeriodSlots(date_range="this_month")),
        ("Expenses yesterday", PeriodSlots(date_range="yesterday")),
        ("How much have I spent in total?", PeriodSlots(date_range="all_time")),
        ("spending in the past 30 days", PeriodSlots(last_days=30)),
        ("Spending in October 2026", PeriodSlots(month="october", year=2026)),
        ("However I spent it", PeriodSlots()),  # "ever" only as a whole word
    ],
)
def test_period_slots_from_text(text, slots):
    assert period_slots_from_text(text) == slots


@pytest.mark.parametrize(
    "text",
    [
        "What did I spend last fortnight?",
        "Spending this quarter",
        "How much did I spend two weeks ago?",
        "Spending since Diwali",
        "What did I spend on Monday?",
        "Spending between 2026-11-01 and 2026-10-01",  # explicit and reversed dates
        "Spending on 2026-11-01",  # a lone date is not a period
        "How much will I spend next month?",
        "Compare this month and last month",  # two periods
        "Spending in the last 3 months",
    ],
)
def test_unrecognised_reversed_or_several_periods_are_reported_not_answered_as_all_time(text):
    with pytest.raises(PeriodError):
        period_slots_from_text(text)


def test_slots_name_one_period_only():
    with pytest.raises(ValidationError):
        PeriodSlots(date_range="today", last_days=7)
    with pytest.raises(ValidationError):
        PeriodSlots(year=2026, last_days=7)
    with pytest.raises(ValidationError):
        PeriodSlots.model_validate({"start_date": "2026-11-01"})  # a range needs both ends
    with pytest.raises(ValidationError):
        PeriodSlots.model_validate({"date_range": "today", "start_date": "2026-11-01", "end_date": "2026-11-02"})
    with pytest.raises(ValidationError):
        PeriodSlots(date_range="fortnight")


# ---- explicit ranges and whole years ------------------------------------------------------


def test_an_explicit_range_is_taken_as_written():
    p = resolve_period(PeriodSlots.model_validate({"start_date": "2026-11-01", "end_date": "2026-11-15"}), TUESDAY)
    assert (p.start, p.end, p.label) == (date(2026, 11, 1), date(2026, 11, 15), "from 1 Nov 2026 to 15 Nov 2026")
    assert from_text("Show my expenses from 1 Nov to 15 Nov")[:2] == (date(2026, 11, 1), date(2026, 11, 15))
    assert from_text("Spending between 3rd Oct 2026 and 9th Oct 2026")[:2] == (date(2026, 10, 3), date(2026, 10, 9))
    # A day and month without a year that has not come yet this year is last year's.
    assert from_text("Spending from 20 Dec to 31 Dec")[:2] == (date(2025, 12, 20), date(2025, 12, 31))


@pytest.mark.parametrize(
    ("slots", "message"),
    [
        ({"start_date": "2026-11-20", "end_date": "2026-11-10"}, "after its end date"),
        ({"start_date": "2026-12-01", "end_date": "2026-12-31"}, "has not started yet"),
        ({"start_date": "2020-01-01", "end_date": "2026-11-24"}, "longer than the two years"),
    ],
)
def test_a_reversed_future_or_too_long_range_is_reported_never_swapped_or_cut(slots, message):
    with pytest.raises(PeriodError, match=message):
        resolve_period(PeriodSlots.model_validate(slots), TUESDAY)


def test_reading_a_reversed_or_impossible_range_reports_it():
    with pytest.raises(PeriodError, match="after its end date"):
        period_slots_from_text("Show my expenses from 20 Nov to 10 Nov", TUESDAY)
    with pytest.raises(PeriodError, match="could not work out a date"):
        period_slots_from_text("Spending from 31 Feb to 3 Mar", TUESDAY)


def test_a_year_on_its_own_is_that_calendar_year():
    assert resolve(year=2025) == (date(2025, 1, 1), date(2025, 12, 31), "in 2025")
    assert from_text("How much did I spend in 2026?")[:2] == (date(2026, 1, 1), date(2026, 12, 31))
    with pytest.raises(PeriodError):
        resolve(year=2027)


def test_two_periods_are_read_in_the_order_they_are_written():
    assert periods_from_text("Compare this month with last month", TUESDAY) == [
        PeriodSlots(date_range="this_month"), PeriodSlots(date_range="last_month"),
    ]
    assert periods_from_text("October 2026 vs September 2026", TUESDAY) == [
        PeriodSlots(month="october", year=2026), PeriodSlots(month="september", year=2026),
    ]
    # "in total" and "overall" mean all time only when no other period is named.
    assert period_slots_from_text("How much did I spend in total last month?") == PeriodSlots(date_range="last_month")
    assert period_slots_from_text("What is my overall spending?") == PeriodSlots(date_range="all_time")


# ---- capping at today ---------------------------------------------------------------------


def test_cap_at_today_ends_the_period_today_and_says_so_far():
    p = cap_at_today(resolve_period(PeriodSlots(date_range="this_month"), TUESDAY), TUESDAY)
    assert (p.start, p.end, p.label, p.days) == (date(2026, 11, 1), TUESDAY, "this month so far", 24)
    past = resolve_period(PeriodSlots(date_range="last_week"), TUESDAY)
    assert cap_at_today(past, TUESDAY) == past
    with pytest.raises(PeriodError):
        cap_at_today(resolve_period(PeriodSlots(date_range="this_month"), TUESDAY), date(2026, 10, 31))


# ---- Asia/Kolkata around midnight ---------------------------------------------------------


@pytest.mark.parametrize(
    ("utc_now", "today", "last_week"),
    [
        # 23:30 IST on Sunday 29 Nov is still Sunday: last week is 16-22 Nov.
        (datetime(2026, 11, 29, 18, 0, tzinfo=UTC), date(2026, 11, 29), (date(2026, 11, 16), date(2026, 11, 22))),
        # 00:15 IST on Monday 30 Nov (still Sunday in UTC): last week is 23-29 Nov.
        (datetime(2026, 11, 29, 18, 45, tzinfo=UTC), date(2026, 11, 30), (date(2026, 11, 23), date(2026, 11, 29))),
        # 00:15 IST on 1 Jan 2027 (still 31 Dec in UTC).
        (datetime(2026, 12, 31, 18, 45, tzinfo=UTC), date(2027, 1, 1), (date(2026, 12, 21), date(2026, 12, 27))),
    ],
)
def test_today_is_the_calendar_day_in_kolkata(monkeypatch, utc_now, today, last_week):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_now.astimezone(tz) if tz else utc_now.replace(tzinfo=None)

    monkeypatch.setattr(settlement_service, "datetime", FrozenDateTime)
    assert date_ranges.today_in_kolkata() == today
    p = resolve_period(PeriodSlots(date_range="last_week"))
    assert (p.start, p.end) == last_week


# ---- T-52 helpers keep their behaviour ----------------------------------------------------


def test_t52_week_month_and_trend_windows_are_unchanged():
    assert week_range(TUESDAY) == (date(2026, 11, 23), date(2026, 11, 29))
    assert month_range(date(2026, 2, 14)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert daily_trend_window(TUESDAY) == (TUESDAY - timedelta(days=29), TUESDAY)
    assert weekly_trend_window(TUESDAY) == (TUESDAY - timedelta(weeks=11), TUESDAY)
    assert monthly_trend_window(TUESDAY) == (date(2025, 11, 1), TUESDAY)
