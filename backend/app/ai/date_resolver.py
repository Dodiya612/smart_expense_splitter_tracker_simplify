"""Deterministic date resolution service scoped to Asia/Kolkata (IST).

Interprets relative date descriptions in code so that the LLM NEVER calculates
authoritative date boundaries.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import ClassVar
from zoneinfo import ZoneInfo

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class ResolvedDateRange:
    """Authoritative date range resolved in Asia/Kolkata timezone."""

    start_date: date | None
    end_date: date | None
    period_label: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "period_label": self.period_label,
        }


class DateResolver:
    """Deterministic date resolver using Asia/Kolkata (IST) timezone."""

    MONTH_NAMES: ClassVar[dict[str, int]] = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    @classmethod
    def get_current_ist_datetime(cls) -> datetime:
        """Get current datetime in Asia/Kolkata timezone."""
        return datetime.now(KOLKATA_TZ)

    @classmethod
    def get_current_ist_date(cls) -> date:
        """Get current date in Asia/Kolkata timezone."""
        return cls.get_current_ist_datetime().date()

    @classmethod
    def resolve_relative_keyword(
        cls, keyword: str, ref_date: date | None = None
    ) -> ResolvedDateRange:
        """Resolve a relative keyword (e.g.

        'last_week', 'this_month') using ref_date in IST.
        """
        today = ref_date or cls.get_current_ist_date()
        clean = keyword.strip().lower().replace("-", "_").replace(" ", "_")

        if clean in ("today",):
            return ResolvedDateRange(
                start_date=today,
                end_date=today,
                period_label="today",
            )

        if clean in ("yesterday",):
            y = today - timedelta(days=1)
            return ResolvedDateRange(
                start_date=y,
                end_date=y,
                period_label="yesterday",
            )

        if clean in ("this_week", "current_week"):
            start_week = today - timedelta(days=today.weekday())  # Monday
            end_week = start_week + timedelta(days=6)  # Sunday
            return ResolvedDateRange(
                start_date=start_week,
                end_date=end_week,
                period_label="this week",
            )

        if clean in ("last_week", "previous_week", "past_week"):
            start_this_week = today - timedelta(days=today.weekday())
            start_last_week = start_this_week - timedelta(days=7)  # Previous Monday
            end_last_week = start_this_week - timedelta(days=1)  # Previous Sunday
            return ResolvedDateRange(
                start_date=start_last_week,
                end_date=end_last_week,
                period_label="last week",
            )

        if clean in ("this_month", "current_month"):
            start_month = date(today.year, today.month, 1)
            _, last_day = calendar.monthrange(today.year, today.month)
            end_month = date(today.year, today.month, last_day)
            return ResolvedDateRange(
                start_date=start_month,
                end_date=end_month,
                period_label="this month",
            )

        if clean in ("last_month", "previous_month", "past_month"):
            if today.month == 1:
                year = today.year - 1
                month = 12
            else:
                year = today.year
                month = today.month - 1
            start_month = date(year, month, 1)
            _, last_day = calendar.monthrange(year, month)
            end_month = date(year, month, last_day)
            return ResolvedDateRange(
                start_date=start_month,
                end_date=end_month,
                period_label="last month",
            )

        if clean in ("this_year", "current_year"):
            start_year = date(today.year, 1, 1)
            end_year = date(today.year, 12, 31)
            return ResolvedDateRange(
                start_date=start_year,
                end_date=end_year,
                period_label="this year",
            )

        if clean in ("last_year", "previous_year", "past_year"):
            start_year = date(today.year - 1, 1, 1)
            end_year = date(today.year - 1, 12, 31)
            return ResolvedDateRange(
                start_date=start_year,
                end_date=end_year,
                period_label="last year",
            )

        if clean in ("last_7_days", "past_7_days"):
            start_d = today - timedelta(days=7)
            return ResolvedDateRange(
                start_date=start_d,
                end_date=today,
                period_label="last 7 days",
            )

        if clean in ("last_30_days", "past_30_days"):
            start_d = today - timedelta(days=30)
            return ResolvedDateRange(
                start_date=start_d,
                end_date=today,
                period_label="last 30 days",
            )

        if clean in ("all_time", "all", "lifetime", "overall"):
            return ResolvedDateRange(
                start_date=None,
                end_date=None,
                period_label="all time",
            )

        # Fallback to None
        return ResolvedDateRange(
            start_date=None,
            end_date=None,
            period_label="custom period",
        )

    @classmethod
    def resolve_from_text(
        cls, text: str, ref_date: date | None = None
    ) -> ResolvedDateRange | None:
        """Scan free-form question text for recognized date keywords or specific month expressions."""
        today = ref_date or cls.get_current_ist_date()
        norm = text.lower()

        # Check explicit relative phrases in order of specificity
        if re.search(r"\blast\s+month\b|\bprevious\s+month\b|\bpast\s+month\b", norm):
            return cls.resolve_relative_keyword("last_month", today)
        if re.search(r"\bthis\s+month\b|\bcurrent\s+month\b", norm):
            return cls.resolve_relative_keyword("this_month", today)
        if re.search(r"\blast\s+week\b|\bprevious\s+week\b|\bpast\s+week\b", norm):
            return cls.resolve_relative_keyword("last_week", today)
        if re.search(r"\bthis\s+week\b|\bcurrent\s+week\b", norm):
            return cls.resolve_relative_keyword("this_week", today)
        if re.search(r"\byesterday\b", norm):
            return cls.resolve_relative_keyword("yesterday", today)
        if re.search(r"\btoday\b", norm):
            return cls.resolve_relative_keyword("today", today)
        if re.search(r"\blast\s+year\b|\bprevious\s+year\b|\bpast\s+year\b", norm):
            return cls.resolve_relative_keyword("last_year", today)
        if re.search(r"\bthis\s+year\b|\bcurrent\s+year\b", norm):
            return cls.resolve_relative_keyword("this_year", today)
        if re.search(r"\blast\s+7\s+days\b|\bpast\s+7\s+days\b", norm):
            return cls.resolve_relative_keyword("last_7_days", today)
        if re.search(r"\blast\s+30\s+days\b|\bpast\s+30\s+days\b", norm):
            return cls.resolve_relative_keyword("last_30_days", today)

        # Check specific named month, e.g. "in October" or "in October 2026"
        month_match = re.search(
            r"\b(in|for|during)?\s*(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b(?:\s+(\d{4}))?",
            norm,
        )
        if month_match:
            month_str = month_match.group(2)
            month_num = cls.MONTH_NAMES.get(month_str)
            if month_num:
                year = int(month_match.group(3)) if month_match.group(3) else today.year
                start_month = date(year, month_num, 1)
                _, last_day = calendar.monthrange(year, month_num)
                end_month = date(year, month_num, last_day)
                month_name = calendar.month_name[month_num]
                return ResolvedDateRange(
                    start_date=start_month,
                    end_date=end_month,
                    period_label=f"{month_name} {year}",
                )

        # Check explicit ISO date YYYY-MM-DD
        iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", norm)
        if iso_match:
            try:
                d = date.fromisoformat(iso_match.group(0))
                return ResolvedDateRange(start_date=d, end_date=d, period_label=d.isoformat())
            except ValueError:
                pass

        return None

    @classmethod
    def resolve(
        cls,
        date_range_keyword: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        query_text: str | None = None,
        ref_date: date | None = None,
    ) -> ResolvedDateRange:
        """Master resolution method.

        Precedence:
        1. date_range_keyword if provided
        2. Explicit start_date / end_date ISO strings if provided
        3. Extracted from query_text
        4. Default: all time
        """
        today = ref_date or cls.get_current_ist_date()

        if date_range_keyword and date_range_keyword.strip():
            res = cls.resolve_relative_keyword(date_range_keyword, today)
            if res.start_date is not None or res.period_label == "all time":
                return res

        if start_date and start_date.strip():
            try:
                s_date = date.fromisoformat(start_date.strip())
                e_date = (
                    date.fromisoformat(end_date.strip())
                    if (end_date and end_date.strip())
                    else s_date
                )
                return ResolvedDateRange(
                    start_date=s_date,
                    end_date=e_date,
                    period_label=f"{s_date.isoformat()} to {e_date.isoformat()}",
                )
            except ValueError:
                pass

        if query_text and query_text.strip():
            extracted = cls.resolve_from_text(query_text, today)
            if extracted:
                return extracted

        return ResolvedDateRange(
            start_date=None,
            end_date=None,
            period_label="all time",
        )
