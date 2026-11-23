"""Password strength estimate on a 0-4 scale (T-50).

Dependency-free and deterministic. The SAME rules are implemented for the mobile app in
``mobile/src/features/auth/utils/passwordStrength.ts``; both are checked against the shared
fixture ``backend/tests/fixtures/password_strength_cases.json`` so the meter the user sees
and the check the server enforces cannot drift apart. Change both files together.

How the score is computed
-------------------------
1. Characters that follow an obvious pattern do not count towards the effective length:
   * a repeat of the previous character ("aaaa"),
   * the third and later characters of a run that steps by one ("abcd", "4321"),
   * characters inside a 4+ character keyboard run ("qwer", "asdf", "7890"),
   * characters inside a common word ("password", "welcome") or inside the user's own
     name or email local part (only the first character of the match counts).
2. The character pool is the sum of the classes present: lowercase 26, uppercase 26,
   digits 10, ASCII symbols and space 33, anything else 100.
3. ``bits = effective_length * log2(pool)``, mapped to a score:
   < 28 -> 0, < 40 -> 1, < 56 -> 2, < 76 -> 3, otherwise 4.
4. A password that IS a common password (lowercased, or reduced to its letters, with or
   without undoing simple letter-for-digit swaps such as "p@ssw0rd") is capped at 1.

This is an estimate, not a guarantee. It is the server's gate for T-50 (score >= 3) and is
deliberately conservative about the patterns people use most.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_SCORE = 3

KEYBOARD_ROWS: tuple[str, ...] = ("1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm")

# Common passwords and base words. Lowercase letters only (that is what a password is
# reduced to before the exact-match check). Kept short on purpose: the pattern rules
# above catch most of the rest.
COMMON_WORDS: tuple[str, ...] = (
    "password", "passwd", "passw", "qwerty", "qwertyuiop", "asdfgh", "zxcvbn", "letmein",
    "welcome", "admin", "administrator", "login", "dragon", "monkey", "football", "cricket",
    "baseball", "iloveyou", "sunshine", "princess", "shadow", "master", "superman", "batman",
    "trustno", "abc", "abcdef", "secret", "freedom", "whatever", "charlie", "michael",
    "jennifer", "hello", "summer", "winter", "spring", "autumn", "flower", "computer",
    "internet", "starwars", "pokemon", "google", "india", "mumbai", "delhi", "krishna",
    "ganesh", "sairam", "omsairam", "jaishreeram", "coinscious", "splittr", "expense",
    "changeme", "default", "access", "mustang", "killer", "pepper", "ginger", "hunter",
    "ranger", "soccer", "hockey", "tigger", "jordan", "harley", "robert", "thomas",
    "daniel", "matrix", "biscuit", "cookie", "chocolate", "butterfly", "lovely", "angel",
)

_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"}

_SCORE_THRESHOLDS: tuple[int, ...] = (28, 40, 56, 76)


@dataclass(frozen=True)
class PasswordStrength:
    score: int
    effective_length: int
    is_common: bool
    feedback: tuple[str, ...] = field(default_factory=tuple)


def _char_class(ch: str) -> str:
    if "a" <= ch <= "z":
        return "lower"
    if "A" <= ch <= "Z":
        return "upper"
    if "0" <= ch <= "9":
        return "digit"
    if " " <= ch <= "~":
        return "symbol"
    return "other"


_POOL = {"lower": 26, "upper": 26, "digit": 10, "symbol": 33, "other": 100}


def _lower_per_char(text: str) -> str:
    """Lowercase one character at a time, keeping a character whose lowercase form is longer
    (for example "İ"), so every index still lines up with the original password."""
    return "".join(low if len(low := ch.lower()) == 1 else ch for ch in text)


def _normalise_leet(lowered: str) -> str:
    return "".join(_LEET.get(ch, ch) for ch in lowered)


def _mark_substrings(haystack: str, needles: Iterable[str], patterned: list[bool]) -> bool:
    """Mark every occurrence of each needle (all but its first character). True if any."""
    found = False
    for needle in needles:
        if len(needle) < 3:
            continue
        start = haystack.find(needle)
        while start != -1:
            found = True
            for i in range(start + 1, start + len(needle)):
                patterned[i] = True
            start = haystack.find(needle, start + 1)
    return found


def _user_tokens(user_inputs: Sequence[str]) -> list[str]:
    tokens: list[str] = []
    for value in user_inputs:
        if not value:
            continue
        lowered = value.strip().lower()
        local = lowered.split("@", 1)[0]
        for part in [local, *local.replace(".", " ").replace("_", " ").replace("-", " ").split(), *lowered.split()]:
            if len(part) >= 3 and part not in tokens:
                tokens.append(part)
    return tokens


def estimate_password_strength(password: str, user_inputs: Sequence[str] = ()) -> PasswordStrength:
    """Score a password 0-4 and explain what would improve it."""
    if not password:
        return PasswordStrength(score=0, effective_length=0, is_common=False, feedback=("Enter a password.",))

    lower = _lower_per_char(password)
    leet = _normalise_leet(lower)
    n = len(password)
    patterned = [False] * n
    has_repeat_or_sequence = False

    for i in range(1, n):
        if password[i] == password[i - 1]:
            patterned[i] = True
            has_repeat_or_sequence = True
        elif i >= 2:
            d1 = ord(password[i - 1]) - ord(password[i - 2])
            d2 = ord(password[i]) - ord(password[i - 1])
            if d1 == d2 and abs(d1) == 1:
                patterned[i] = True
                has_repeat_or_sequence = True

    for row in KEYBOARD_ROWS:
        for line in (row, row[::-1]):
            for j in range(0, n - 3):
                if lower[j : j + 4] in line:
                    has_repeat_or_sequence = True
                    for k in range(j + 1, j + 4):
                        patterned[k] = True

    has_common_word = _mark_substrings(leet, COMMON_WORDS, patterned)
    has_user_info = _mark_substrings(lower, _user_tokens(user_inputs), patterned)

    effective_length = sum(1 for p in patterned if not p)
    classes = {_char_class(ch) for ch in password}
    pool = sum(_POOL[c] for c in classes)
    bits = effective_length * math.log2(pool) if pool > 1 else 0.0

    score = 4
    for index, threshold in enumerate(_SCORE_THRESHOLDS):
        if bits < threshold:
            score = index
            break

    plain_letters = "".join(ch for ch in lower if "a" <= ch <= "z")
    leet_letters = "".join(ch for ch in leet if "a" <= ch <= "z")
    is_common = any(form in COMMON_WORDS for form in (lower, plain_letters, leet_letters))
    if is_common:
        score = min(score, 1)

    feedback: list[str] = []
    if n < MIN_PASSWORD_LENGTH:
        feedback.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if is_common:
        feedback.append("This is a commonly used password. Choose something less predictable.")
    elif has_common_word:
        feedback.append("Avoid common words like \"password\" or \"welcome\".")
    if has_user_info:
        feedback.append("Do not include your name or email address.")
    if has_repeat_or_sequence:
        feedback.append("Avoid repeated characters and sequences like \"abc\", \"1234\" or \"qwerty\".")
    if score < MIN_PASSWORD_SCORE and len(classes) < 3:
        feedback.append("Mix uppercase and lowercase letters, numbers and symbols.")
    if score < MIN_PASSWORD_SCORE:
        feedback.append("Add more characters or another unrelated word.")

    return PasswordStrength(
        score=score,
        effective_length=effective_length,
        is_common=is_common,
        feedback=tuple(feedback),
    )
