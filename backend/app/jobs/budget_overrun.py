"""Budget overrun alert job (T-56).

This module provides a small helper that can be called from any place where a
budget check discovers an excess.  It builds a deduped `budget_overrun`
notification and persists it via the shared notification centre.
"""

from __future__ import annotations

from datetime import datetime

from app.jobs.notification_center import send_notification


def budget_overrun_alert(
    user_id: str,
    budget_id: str,
    period: str,
    spent_paise: int,
    limit_paise: int,
) -> None:
    """Emit a one‑time over‑budget notification.

    * ``user_id`` – the UUID of the user.
    * ``budget_id`` – identifier of the budget that was exceeded.
    * ``period`` – a string describing the period (e.g. ``"2023-07"`` for a
      monthly budget or ``"2023-W30"`` for a weekly budget).
    * ``spent_paise`` / ``limit_paise`` – monetary amounts in paise.

    The dedupe key is ``budget_overrun:{user_id}:{budget_id}:{period}`` which
    guarantees a single alert per user‑budget‑period even if the function is
    called multiple times (e.g. after a restart).
    """

    payload = {
        "budget_id": budget_id,
        "period": period,
        "spent_paise": spent_paise,
        "limit_paise": limit_paise,
    }
    dedupe_key = f"budget_overrun:{user_id}:{budget_id}:{period}"
    send_notification(
        user_id=user_id,
        kind="budget_overrun",
        payload=payload,
        dedupe_key=dedupe_key,
        title="Budget exceeded",
        body=f"You have exceeded your budget for period {period}.",
    )
