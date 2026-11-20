"""In-memory stand-in for the notification store, used by the fake-session API tests.

The real store (``app.services.notifications._persist``) talks to PostgreSQL with
``INSERT ... ON CONFLICT DO NOTHING``; that behaviour is verified against a real
database in tests/test_notifications_pg.py. These fake-session suites only need to
observe *which* notifications the write paths try to store, so conftest swaps
``_persist`` for ``fake_persist`` below, which mimics the (user, dedupe_key)
uniqueness and the "switched off" preference.
"""

from __future__ import annotations

from app.services.notifications import NotificationEvent

_stored: list[NotificationEvent] = []
_keys: set[tuple[str, str]] = set()
_disabled: set[tuple[str, str]] = set()


def clear_emitted_notifications() -> None:
    _stored.clear()
    _keys.clear()
    _disabled.clear()


def get_emitted_notifications() -> list[NotificationEvent]:
    return list(_stored)


def disable_kind(user_id: object, kind: str) -> None:
    _disabled.add((str(user_id), kind))


async def fake_persist(events: list[NotificationEvent]) -> list[NotificationEvent]:
    inserted: list[NotificationEvent] = []
    for event in events:
        if (event.user_id, event.kind) in _disabled:
            continue
        key = (event.user_id, event.dedupe_key)
        if key in _keys:
            continue
        _keys.add(key)
        _stored.append(event)
        inserted.append(event)
    return inserted


async def no_database_membership(_db: object, _group_id: object) -> None:
    """Stand-in for notifications.active_member_roles in fake-session tests."""
    return None
