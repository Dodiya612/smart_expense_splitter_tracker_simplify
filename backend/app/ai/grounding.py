"""Grounding guard for assistant answers (T-57 / US-24).

Every figure in an answer comes from the backend. The language model never writes
a number itself:

1. The model writes its sentence with placeholders such as ``{total}`` or
   ``{period}``; ``fill_placeholders`` rejects number words, non-Latin digits and
   unknown placeholders in the model's own text, then fills the placeholders with
   values formatted in code.
2. ``find_violations`` is the backstop on the final text, including any digits
   the model wrote itself instead of a placeholder. It is type-aware:
   rupee amounts are compared with the rupee figures the tool returned (exact
   paise), percentages with the percentages the tool computed, dates as whole
   dates with the period and bucket dates, and any other number with the counts.
   Indian (₹1,23,456.00) and western (₹123,456.00) digit grouping are both read;
   anything else, a sign, or a shorthand such as "2.4k" is a violation.

When either step fails the caller uses the tool's template sentence instead.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_ANSWER_LENGTH = 500


# ---------------------------------------------------------------------------
# Formatting (the only place answer numbers are written)
# ---------------------------------------------------------------------------


def format_rupees(paise: int) -> str:
    """₹1,23,456.78 - Indian digit grouping, always two decimals."""
    sign = "-" if paise < 0 else ""
    rupees, rest = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        digits = ",".join([head, *pairs, tail])
    return f"{sign}₹{digits}.{rest:02d}"


def format_count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def percentage(part: int, whole: int) -> Decimal:
    """part / whole as a percentage with one decimal place (half up)."""
    if whole <= 0:
        return Decimal("0.0")
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def format_percent(value: Decimal) -> str:
    return f"{value}%"


# ---------------------------------------------------------------------------
# What a tool result allows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AllowedFigures:
    amounts_paise: frozenset[int]
    counts: frozenset[int]
    percentages: frozenset[Decimal]
    dates: frozenset[date]
    #: Phrases written by code that may contain digits, e.g. the period label
    #: "in the last 7 days". They are accepted only as whole phrases, so the 7 in
    #: them never makes "7 expenses" acceptable.
    phrases: frozenset[str] = frozenset()

    @property
    def months(self) -> frozenset[tuple[int, int]]:
        return frozenset((d.year, d.month) for d in self.dates)


# ---------------------------------------------------------------------------
# Step 1: placeholders in the model's text
# ---------------------------------------------------------------------------

_NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety|hundreds?|thousands?|lakhs?|lacs?|crores?|millions?|billions?|dozens?|half|twice|"
    r"thrice|double|triple|quarter)\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _has_non_latin_digit(text: str) -> bool:
    """Devanagari and other non-Latin digits, and numeric symbols such as '½'."""
    return any((ch.isdigit() and not ch.isascii()) or (ch.isnumeric() and not ch.isdigit()) for ch in text)


def fill_placeholders(text: str | None, values: dict[str, str]) -> str | None:
    """Fill the model's placeholders, or None if its own text cannot be checked.

    Number words and non-Latin digits cannot be verified, so they are rejected here;
    digits are left for ``find_violations``.
    """
    if not text:
        return None
    text = text.strip()
    if not text or len(text) > MAX_ANSWER_LENGTH:
        return None
    if _has_non_latin_digit(text) or _NUMBER_WORDS.search(text):
        return None
    names = _PLACEHOLDER.findall(text)
    if not names or any(name not in values for name in names):
        return None
    if "{" in _PLACEHOLDER.sub("", text) or "}" in _PLACEHOLDER.sub("", text):
        return None
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


# ---------------------------------------------------------------------------
# Step 2: type-aware check of the final text
# ---------------------------------------------------------------------------

_NUM = r"\d+(?:,\d+)*(?:\.\d+)?"
_WESTERN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_INDIAN = re.compile(r"\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?")
_MONTH_ALT = "|".join(
    sorted({*(calendar.month_name[i] for i in range(1, 13)), *(calendar.month_abbr[i] for i in range(1, 13)), "Sept"},
           key=len, reverse=True)
)
_MONTH_INDEX = {calendar.month_name[i].lower(): i for i in range(1, 13)} | {
    calendar.month_abbr[i].lower(): i for i in range(1, 13)
} | {"sept": 9}

_DATE_DMY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_YEAR = re.compile(rf"\b({_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
_MONEY_BEFORE = re.compile(
    rf"(?P<sign>-\s*)?(?:₹|\brs\.?|\binr)\s*(?P<inner>-?)\s*(?P<raw>{_NUM})"
    r"\s*(?P<suffix>k|l|cr|lakhs?|lacs?|crores?|mn|million|thousand)?\b",
    re.IGNORECASE,
)
_MONEY_AFTER = re.compile(
    rf"(?P<sign>-?)(?P<raw>{_NUM})\s*(?P<suffix>k|l|cr|lakhs?|crores?)?\s*(?:rupees|rs\b|inr\b)", re.IGNORECASE
)
_PERCENT = re.compile(rf"(-?)({_NUM})\s*(?:%|percent\b|per\s+cent\b)", re.IGNORECASE)
_BARE = re.compile(rf"(-?)({_NUM})([a-z]*)", re.IGNORECASE)
_ORDINAL_SUFFIXES = {"", "st", "nd", "rd", "th"}


def _parse_number(raw: str) -> Decimal | None:
    """The value of a written number, or None when its digit grouping is not valid."""
    if "," in raw and not (_WESTERN.fullmatch(raw) or _INDIAN.fullmatch(raw)):
        return None
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _blank(text: str, span: tuple[int, int]) -> str:
    start, end = span
    return text[:start] + " " * (end - start) + text[end:]


def find_violations(text: str, allowed: AllowedFigures) -> list[str]:
    """Every number in ``text`` that the tool result does not support (empty when grounded)."""
    violations: list[str] = []
    if _has_non_latin_digit(text):
        violations.append("non-Latin digits")
    if _NUMBER_WORDS.search(text):
        violations.append("number written in words")
    work = text
    for phrase in sorted(allowed.phrases, key=len, reverse=True):
        for match in re.finditer(re.escape(phrase), work, re.IGNORECASE):
            work = _blank(work, match.span())

    for match in _DATE_DMY.finditer(work):
        try:
            d = date(int(match.group(3)), _MONTH_INDEX[match.group(2).lower()], int(match.group(1)))
        except ValueError:
            d = None
        if d is None or d not in allowed.dates:
            violations.append(match.group(0))
        work = _blank(work, match.span())
    for match in _DATE_ISO.finditer(work):
        try:
            d = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            d = None
        if d is None or d not in allowed.dates:
            violations.append(match.group(0))
        work = _blank(work, match.span())
    for match in _MONTH_YEAR.finditer(work):
        if (int(match.group(2)), _MONTH_INDEX[match.group(1).lower()]) not in allowed.months:
            violations.append(match.group(0))
        work = _blank(work, match.span())

    for pattern in (_MONEY_BEFORE, _MONEY_AFTER):
        for match in pattern.finditer(work):
            groups = match.groupdict()
            sign = (groups["sign"] or "") + (groups.get("inner") or "")
            raw, suffix = groups["raw"], groups["suffix"]
            value = _parse_number(raw)
            paise = value * 100 if value is not None else None
            if (
                sign
                or suffix
                or paise is None
                or paise != paise.to_integral_value()
                or int(paise) not in allowed.amounts_paise
            ):
                violations.append(match.group(0).strip())
            work = _blank(work, match.span())

    for match in _PERCENT.finditer(work):
        value = _parse_number(match.group(2))
        if match.group(1) or value is None or value not in allowed.percentages:
            violations.append(match.group(0).strip())
        work = _blank(work, match.span())

    for match in _BARE.finditer(work):
        sign, raw, suffix = match.group(1), match.group(2), match.group(3).lower()
        value = _parse_number(raw)
        if (
            sign
            or suffix not in _ORDINAL_SUFFIXES
            or value is None
            or value != value.to_integral_value()
            or int(value) not in allowed.counts
        ):
            violations.append(match.group(0).strip())
    return violations
