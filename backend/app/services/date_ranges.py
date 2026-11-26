"""Calendar periods in Asia/Kolkata (US-12 / US-24).

The single date resolver for the analytics query tools (T-52) and the assistant
(T-57). Dates are always resolved here, in code, never by a language model:

- "today" is the calendar day in Asia/Kolkata (``settlement_service.today_in_kolkata``).
- Weeks run Monday to Sunday; "last week" is the previous Monday to Sunday.
- "last N days" is exactly N calendar days ending today.
- A month named without a year is the most recent such month that has started
  (this month or earlier), never a future one. A year on its own is that
  calendar year.
- An explicit range ("from 1 Nov to 15 Nov") is taken as written; a range that
  ends before it starts, starts in the future or is longer than two years is
  reported, never swapped or cut. Day-and-month dates without a year both get
  the most recent year in which the first date has started.
- "all time" is capped at the longest range the analytics service accepts
  (``MAX_RANGE_DAYS``) and is labelled as such.
- A question asking for no particular period gets the analytics default:
  the 1st of this month to today.

Periods are described by ``PeriodSlots`` (filled by the question parser or the
language model) and turned into a ``Period`` by ``resolve_period``. Anything that
cannot be resolved raises ``PeriodError`` so the caller can say so instead of
answering for a different period.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.analytics_service import MAX_RANGE_DAYS
from app.services.settlement_service import today_in_kolkata

__all__ = [
    "MAX_RANGE_DAYS",
    "Month",
    "Period",
    "PeriodError",
    "PeriodSlots",
    "RelativePeriod",
    "cap_at_today",
    "daily_trend_window",
    "format_day",
    "monthly_trend_window",
    "month_range",
    "period_slots_from_text",
    "periods_from_text",
    "resolve_period",
    "today_in_kolkata",
    "week_range",
    "weekly_trend_window",
]


class PeriodError(ValueError):
    """The period asked for cannot be resolved (unknown, reversed, future or too long)."""


class RelativePeriod(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    THIS_YEAR = "this_year"
    LAST_YEAR = "last_year"
    ALL_TIME = "all_time"


class Month(StrEnum):
    JANUARY = "january"
    FEBRUARY = "february"
    MARCH = "march"
    APRIL = "april"
    MAY = "may"
    JUNE = "june"
    JULY = "july"
    AUGUST = "august"
    SEPTEMBER = "september"
    OCTOBER = "october"
    NOVEMBER = "november"
    DECEMBER = "december"


MONTH_NUMBERS: dict[Month, int] = {m: i for i, m in enumerate(Month, start=1)}


class PeriodSlots(BaseModel):
    """How a question names its period. At most one of the four ways may be used."""

    model_config = ConfigDict(extra="forbid")

    date_range: RelativePeriod | None = Field(default=None, description="A relative period keyword.")
    month: Month | None = Field(default=None, description="A calendar month by name.")
    year: int | None = Field(
        default=None, ge=2000, le=2100, description="Year of the named month, or a whole calendar year on its own."
    )
    last_days: int | None = Field(
        default=None, ge=1, le=MAX_RANGE_DAYS, description="The last N days, including today."
    )
    start_date: date | None = Field(
        default=None, description="First day of a range, only when the question writes the date itself."
    )
    end_date: date | None = Field(
        default=None, description="Last day of a range, only when the question writes the date itself."
    )

    @model_validator(mode="after")
    def _one_way_only(self) -> PeriodSlots:
        explicit = (self.start_date, self.end_date)
        if any(d is not None for d in explicit) and None in explicit:
            raise ValueError("start_date and end_date go together.")
        named = self.month is not None or self.year is not None
        used = [self.date_range is not None, named, self.last_days is not None, self.start_date is not None]
        if sum(used) > 1:
            raise ValueError("Use only one of date_range, month/year, last_days or start_date/end_date.")
        return self

    def is_empty(self) -> bool:
        return not self.model_dump(exclude_none=True)


@dataclass(frozen=True)
class Period:
    """An inclusive calendar range with the words used for it in answers."""

    start: date
    end: date
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


# ---------------------------------------------------------------------------
# Calendar helpers (shared with the T-52 analytics query-tool endpoints)
# ---------------------------------------------------------------------------


def week_range(reference: date) -> tuple[date, date]:
    """Monday-to-Sunday range containing ``reference``."""
    start = reference - timedelta(days=reference.weekday())  # Monday
    end = start + timedelta(days=6)  # Sunday
    return start, end


def month_range(reference: date) -> tuple[date, date]:
    """First and last day of the month containing ``reference``."""
    start = reference.replace(day=1)
    end = reference.replace(day=calendar.monthrange(reference.year, reference.month)[1])
    return start, end


def daily_trend_window(today: date) -> tuple[date, date]:
    """The last 30 days, inclusive of today."""
    return today - timedelta(days=29), today


def weekly_trend_window(today: date) -> tuple[date, date]:
    """Today and the 11 weeks before it (12 weekly buckets)."""
    return today - timedelta(weeks=11), today


def monthly_trend_window(today: date) -> tuple[date, date]:
    """From the 1st of the month twelve months before this one, to today."""
    start = today.replace(day=1) - timedelta(days=1)  # previous month end
    start = (start.replace(day=1) - timedelta(days=1)).replace(day=1)
    for _ in range(10):
        start = (start.replace(day=1) - timedelta(days=1)).replace(day=1)
    return start, today


def all_time_range(today: date) -> tuple[date, date]:
    """The longest range the analytics service accepts, ending today."""
    return today - timedelta(days=MAX_RANGE_DAYS - 1), today


def format_day(d: date) -> str:
    """'16 Nov 2026' - the date format used in assistant answers."""
    return f"{d.day} {calendar.month_abbr[d.month]} {d.year}"


# ---------------------------------------------------------------------------
# Resolving period slots
# ---------------------------------------------------------------------------


def _relative(keyword: RelativePeriod, today: date) -> Period:
    if keyword is RelativePeriod.TODAY:
        return Period(today, today, "today")
    if keyword is RelativePeriod.YESTERDAY:
        y = today - timedelta(days=1)
        return Period(y, y, "yesterday")
    if keyword is RelativePeriod.THIS_WEEK:
        return Period(*week_range(today), "this week")
    if keyword is RelativePeriod.LAST_WEEK:
        return Period(*week_range(today - timedelta(days=7)), "last week")
    if keyword is RelativePeriod.THIS_MONTH:
        return Period(*month_range(today), "this month")
    if keyword is RelativePeriod.LAST_MONTH:
        return Period(*month_range(today.replace(day=1) - timedelta(days=1)), "last month")
    if keyword is RelativePeriod.THIS_YEAR:
        return Period(date(today.year, 1, 1), date(today.year, 12, 31), "this year")
    if keyword is RelativePeriod.LAST_YEAR:
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last year")
    # ALL_TIME: the analytics service accepts at most MAX_RANGE_DAYS, so say so.
    return Period(*all_time_range(today), "in the last 2 years")


def _named_month(month: Month, year: int | None, today: date) -> Period:
    number = MONTH_NUMBERS[month]
    if year is None:
        year = today.year if number <= today.month else today.year - 1
    start = date(year, number, 1)
    if start > today:
        raise PeriodError(f"{calendar.month_name[number]} {year} has not started yet.")
    end = date(year, number, calendar.monthrange(year, number)[1])
    return Period(start, end, f"in {calendar.month_name[number]} {year}")


def _whole_year(year: int, today: date) -> Period:
    if year > today.year:
        raise PeriodError(f"{year} has not started yet.")
    return Period(date(year, 1, 1), date(year, 12, 31), f"in {year}")


def _explicit(start: date, end: date, today: date) -> Period:
    if start > end:
        raise PeriodError("The start date of that range is after its end date.")
    if start > today:
        raise PeriodError("That period has not started yet.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise PeriodError("That period is longer than the two years I can look at.")
    return Period(start, end, f"from {format_day(start)} to {format_day(end)}")


def resolve_period(slots: PeriodSlots, today: date | None = None) -> Period:
    """Turn period slots into an inclusive range in Asia/Kolkata."""
    today = today or today_in_kolkata()
    if slots.date_range is not None:
        return _relative(slots.date_range, today)
    if slots.month is not None:
        return _named_month(slots.month, slots.year, today)
    if slots.year is not None:
        return _whole_year(slots.year, today)
    if slots.last_days is not None:
        n = slots.last_days
        label = "today" if n == 1 else f"in the last {n} days"
        return Period(today - timedelta(days=n - 1), today, label)
    if slots.start_date is not None and slots.end_date is not None:
        return _explicit(slots.start_date, slots.end_date, today)
    # No period named: the analytics default (1st of this month to today).
    return Period(today.replace(day=1), today, "this month so far")


def cap_at_today(period: Period, today: date | None = None) -> Period:
    """End the period today at the latest; the label then says 'so far'."""
    today = today or today_in_kolkata()
    if period.start > today:
        raise PeriodError("That period has not started yet.")
    if period.end <= today:
        return period
    label = period.label if period.label.endswith("so far") else f"{period.label} so far"
    return Period(period.start, today, label)


# ---------------------------------------------------------------------------
# Reading periods from a question (offline parser)
# ---------------------------------------------------------------------------

_MONTH_WORDS: dict[str, Month] = {m.value: m for m in Month}
_MONTH_WORDS.update(
    {
        "jan": Month.JANUARY,
        "feb": Month.FEBRUARY,
        "mar": Month.MARCH,
        "apr": Month.APRIL,
        "jun": Month.JUNE,
        "jul": Month.JULY,
        "aug": Month.AUGUST,
        "sep": Month.SEPTEMBER,
        "sept": Month.SEPTEMBER,
        "oct": Month.OCTOBER,
        "nov": Month.NOVEMBER,
        "dec": Month.DECEMBER,
    }
)
_MONTH_ALT = "|".join(sorted(_MONTH_WORDS, key=len, reverse=True))

_RELATIVE_PATTERNS: list[tuple[re.Pattern[str], RelativePeriod]] = [
    (re.compile(r"\btoday\b"), RelativePeriod.TODAY),
    (re.compile(r"\byesterday\b"), RelativePeriod.YESTERDAY),
    (re.compile(r"\b(?:this|current)\s+week\b"), RelativePeriod.THIS_WEEK),
    (re.compile(r"\b(?:last|previous|past)\s+week\b"), RelativePeriod.LAST_WEEK),
    (re.compile(r"\b(?:this|current)\s+month\b"), RelativePeriod.THIS_MONTH),
    (re.compile(r"\b(?:last|previous|past)\s+month\b"), RelativePeriod.LAST_MONTH),
    (re.compile(r"\b(?:this|current)\s+year\b"), RelativePeriod.THIS_YEAR),
    (re.compile(r"\b(?:last|previous|past)\s+year\b"), RelativePeriod.LAST_YEAR),
    (re.compile(r"\b(?:all\s+time|ever|lifetime)\b"), RelativePeriod.ALL_TIME),
]
# "overall" and "in total" mean all time only when the question names no other period
# ("How much did I spend in total last month?" is last month).
_ALL_TIME_IF_ALONE = re.compile(r"\b(?:overall|in\s+total)\b")
_LAST_DAYS = re.compile(r"\b(?:last|past|previous)\s+(\d{1,4})\s+days?\b")
_DAY_MONTH = rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?(?:,?\s+(\d{{4}}))?"
_EXPLICIT_DMY = re.compile(rf"\b(?:from|between)\s+{_DAY_MONTH}\s+(?:to|and|till|until|-)\s+{_DAY_MONTH}\b")
_EXPLICIT_ISO = re.compile(
    r"\b(?:from|between)\s+(\d{4})-(\d{2})-(\d{2})\s+(?:to|and|till|until|-)\s+(\d{4})-(\d{2})-(\d{2})\b"
)
_MONTH_NAME = re.compile(rf"\b({_MONTH_ALT})\b(?:\s+(\d{{4}})\b)?")
_YEAR = re.compile(r"\b(?:in|for|during|of)\s+(\d{4})\b")
# "May" is a month only after a preposition ("in May") or before a year ("May 2026").
_MAY_AS_MONTH = re.compile(r"\b(?:in|for|during|of|since|last)\s+may\b|\bmay\s+\d{4}\b")
# Period words this resolver does not understand: report them instead of guessing.
_UNKNOWN_PERIOD = re.compile(
    r"\b(?:fortnight|quarter|q[1-4]|weekends?|semester|ago|since|between|until|till)\b"
    r"|\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b"
    r"|\b(?:next|coming)\s+(?:week|month|year|\d+\s+days?)\b"
    r"|\b(?:last|past|previous)\s+\d+\s+(?:weeks?|months?|years?)\b"
    r"|\b(?:last|past|previous)\s+(?:few|couple|several)\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20|21)\d{2}\b"
)


def _blank(text: str, span: tuple[int, int]) -> str:
    start, end = span
    return text[:start] + " " * (end - start) + text[end:]


def _make_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise PeriodError("I could not work out a date in your question.") from None


def _explicit_from_words(match: re.Match[str], today: date) -> PeriodSlots:
    d1, m1, y1, d2, m2, y2 = match.groups()
    n1, n2 = MONTH_NUMBERS[_MONTH_WORDS[m1]], MONTH_NUMBERS[_MONTH_WORDS[m2]]
    given = [_check_year(int(y)) for y in (y1, y2) if y is not None]
    if not given:
        # Both dates get the most recent year in which the first one has started.
        start_year = end_year = today.year if (n1, int(d1)) <= (today.month, today.day) else today.year - 1
    else:
        start_year = int(y1) if y1 is not None else given[0]
        end_year = int(y2) if y2 is not None else given[0]
    start = _make_date(start_year, n1, int(d1))
    end = _make_date(end_year, n2, int(d2))
    return PeriodSlots(start_date=start, end_date=end)


def _check_year(year: int) -> int:
    if not 2000 <= year <= 2100:
        raise PeriodError("I could not work out the year in your question.")
    return year


def periods_from_text(text: str, today: date | None = None) -> list[PeriodSlots]:
    """Every distinct period a question names, in the order they appear.

    Raises PeriodError for a period this resolver does not understand, or for an
    explicit range that cannot be resolved (reversed, future, too long).
    """
    today = today or today_in_kolkata()
    work = text.lower()
    found: list[tuple[int, PeriodSlots]] = []

    for match in _EXPLICIT_DMY.finditer(work):
        found.append((match.start(), _explicit_from_words(match, today)))
        work = _blank(work, match.span())
    for match in _EXPLICIT_ISO.finditer(work):
        y1, m1, d1, y2, m2, d2 = (int(g) for g in match.groups())
        slots = PeriodSlots(start_date=_make_date(y1, m1, d1), end_date=_make_date(y2, m2, d2))
        found.append((match.start(), slots))
        work = _blank(work, match.span())
    for _, slots in found:
        resolve_period(slots, today)  # reversed, future or too long: say so now

    for pattern, keyword in _RELATIVE_PATTERNS:
        for match in pattern.finditer(work):
            found.append((match.start(), PeriodSlots(date_range=keyword)))
            work = _blank(work, match.span())
    for match in _LAST_DAYS.finditer(work):
        days = int(match.group(1))
        if not 1 <= days <= MAX_RANGE_DAYS:
            raise PeriodError("That period is longer than the two years I can look at.")
        found.append((match.start(), PeriodSlots(last_days=days)))
        work = _blank(work, match.span())
    may_is_month = bool(_MAY_AS_MONTH.search(work))
    for match in _MONTH_NAME.finditer(work):
        word = match.group(1)
        if word == "may" and not may_is_month:
            continue
        year = _check_year(int(match.group(2))) if match.group(2) else None
        found.append((match.start(), PeriodSlots(month=_MONTH_WORDS[word], year=year)))
        work = _blank(work, match.span())
    for match in _YEAR.finditer(work):
        found.append((match.start(), PeriodSlots(year=_check_year(int(match.group(1))))))
        work = _blank(work, match.span())

    if _UNKNOWN_PERIOD.search(work):
        raise PeriodError("I could not work out the period in your question.")
    if not found:
        match = _ALL_TIME_IF_ALONE.search(work)
        if match:
            found.append((match.start(), PeriodSlots(date_range=RelativePeriod.ALL_TIME)))

    ordered: list[PeriodSlots] = []
    for _, slots in sorted(found, key=lambda item: item[0]):
        if slots not in ordered:
            ordered.append(slots)
    return ordered


def period_slots_from_text(text: str, today: date | None = None) -> PeriodSlots:
    """The one period a question names; no period named gives empty slots.

    Raises PeriodError as ``periods_from_text`` does, and when the question names
    more than one period.
    """
    found = periods_from_text(text, today)
    if len(found) > 1:
        raise PeriodError("I can answer for one period at a time.")
    return found[0] if found else PeriodSlots()
