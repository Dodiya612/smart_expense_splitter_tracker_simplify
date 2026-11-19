"""In-memory stand-in for the rate-limit counter store and clock (T-39).

The real store (app/core/rate_limiter.py ``_store_*``) is SQL against PostgreSQL; its atomicity
and concurrency are verified on a real database in tests/test_rate_limit_pg.py. The
fake-session API tests only need the limiter's logic (windows, hashing, fail-closed, 429/503
mapping, refunds) on top of a store with the same semantics, so conftest swaps the four store
functions and ``_now`` for the ones below.

The clock is frozen at midnight UTC so a test can never straddle a fixed-window boundary;
``advance`` moves it explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

START = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC)

_rows: dict[tuple[str, str, datetime], tuple[int, datetime]] = {}
_clock = {"now": START}
_state = {"fail": False}


def reset() -> None:
    _rows.clear()
    _clock["now"] = START
    _state["fail"] = False


def now() -> datetime:
    return _clock["now"]


def advance(seconds: float) -> None:
    _clock["now"] = _clock["now"] + timedelta(seconds=seconds)


def set_failing(failing: bool) -> None:
    """Make every store call raise, as if the database were unreachable."""
    _state["fail"] = failing


def count_for(scope: str, identifier_hash: str | None = None) -> int:
    """Total of all buckets for a scope (optionally one identifier hash)."""
    return sum(
        c for (s, h, _), (c, _) in _rows.items()
        if s == scope and (identifier_hash is None or h == identifier_hash)
    )


def scopes() -> set[str]:
    return {s for (s, _, _) in _rows}


def _check() -> None:
    if _state["fail"]:
        raise RuntimeError("simulated database outage")


async def store_increment(scope: str, identifier_hash: str, window_start: datetime, expires_at: datetime) -> int:
    _check()
    key = (scope, identifier_hash, window_start)
    count = _rows.get(key, (0, expires_at))[0] + 1
    _rows[key] = (count, expires_at)
    return count


async def store_decrement(scope: str, identifier_hash: str, window_start: datetime) -> None:
    _check()
    key = (scope, identifier_hash, window_start)
    if key in _rows:
        count, expires = _rows[key]
        _rows[key] = (max(count - 1, 0), expires)


async def store_clear(scope: str, identifier_hash: str) -> None:
    _check()
    for key in [k for k in _rows if k[0] == scope and k[1] == identifier_hash]:
        del _rows[key]


async def store_purge(cutoff: datetime, batch: int) -> int:
    _check()
    expired = [k for k, (_, exp) in _rows.items() if exp < cutoff][:batch]
    for key in expired:
        del _rows[key]
    return len(expired)
