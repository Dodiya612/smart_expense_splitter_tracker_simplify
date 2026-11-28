"""Weekly summary job for T‑56.

Runs every Monday (Asia/Kolkata) and sends a notification to each active user
containing a summary of their spending for the previous week (Monday–Sunday).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.jobs.notification_center import send_notification
from app.services.user_service import get_all_active_users  # hypothetical service
from app.services.budget_service import get_user_weekly_report  # hypothetical


def iso_week(dt: datetime) -> str:
    """Return ISO week string like '2023-W45'."""
    return dt.isocalendar().to_string()


def weekly_summary_job() -> None:
    """Background job that emits weekly summary notifications.

    The job is scheduled via APScheduler in ``app.main``.  It iterates over all
    active users, builds a report for the previous week, and calls the
    ``send_notification`` helper with a dedupe key that guarantees one message
    per user per week.
    """

    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # Asia/Kolkata
    # Previous week (Monday–Sunday)
    last_monday = now - timedelta(days=now.weekday() + 7)
    week_start = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

    for user in get_all_active_users():
        report = get_user_weekly_report(user.id, week_start, week_end)
        payload = {"report": report, "period": f"{week_start.date()} – {week_end.date()}"}
        dedupe_key = f"weekly_summary:{user.id}:{iso_week(week_start)}"
        send_notification(
            user_id=str(user.id),
            kind="weekly_summary",
            payload=payload,
            dedupe_key=dedupe_key,
            title="Weekly spending summary",
            body=f"Your spending summary for week {iso_week(week_start)} is ready.",
        )
