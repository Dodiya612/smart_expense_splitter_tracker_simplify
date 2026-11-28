"""Congratulations job (T-56).

Runs on the last day of each month (Asia/Kolkata) and sends a `congratulations`
notification to users who stayed within all of their budgets for the period.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.jobs.notification_center import send_notification
from app.services.user_service import get_all_active_users  # hypothetical helper
from app.services.budget_service import user_stayed_within_budgets  # hypothetical


def month_end_congratulations_job() -> None:
    """Emit a congratulations notification for every user that stayed within budget.

    The job is scheduled in ``app.main`` with a ``CronTrigger(day="last")``.
    It builds a dedupe key of the form ``congratulations:{user_id}:{YYYYMM}`` so a
    user receives at most one congratulatory message per month.
    """

    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # Asia/Kolkata
    period = now.strftime("%Y%m")  # e.g. "202311"

    for user in get_all_active_users():
        if user_stayed_within_budgets(user.id, period):
            dedupe_key = f"congratulations:{user.id}:{period}"
            send_notification(
                user_id=str(user.id),
                kind="congratulations",
                payload={"period": period},
                dedupe_key=dedupe_key,
                title="Congratulations!",
                body=f"You stayed within budget for {period}. Great job!",
            )
