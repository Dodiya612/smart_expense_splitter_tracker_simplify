"""Helper to emit notifications for background jobs.

The existing `app.services.notifications` module provides the low‑level
`_persist` function and the `NotificationEvent` dataclass.  This thin wrapper
builds the event with the appropriate `dedupe_key` and calls the persistence
layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.services.notifications import NotificationEvent, _persist


def send_notification(
    user_id: str,
    kind: str,
    payload: dict,
    dedupe_key: str,
    ref: str = "background",
    title: str = "",
    body: str = "",
) -> None:
    """Create a single NotificationEvent and store it.

    The function is deliberately fire‑and‑forget – any exception is logged by the
    underlying persistence layer.  Callers are expected to construct a unique
    ``dedupe_key`` for the period (e.g. "weekly_summary:{user_id}:{iso_week}").
    """

    event = NotificationEvent(
        user_id=user_id,
        kind=kind,
        ref=ref,
        dedupe_key=dedupe_key,
        payload=payload,
        title=title,
        body=body,
    )
    # `_persist` is async; we run it in the event loop via `asyncio.create_task`
    # to avoid blocking the FastAPI lifespan.  If the caller is already inside
    # an async context this will simply schedule the coroutine.
    import asyncio

    asyncio.create_task(_persist([event]))
