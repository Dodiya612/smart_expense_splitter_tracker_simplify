"""Fast tests for recurring expenses (US-14 / T-44): no database.

Pure date maths and state transitions, the 24-hour notice timing in Asia/Kolkata and its
dedupe (in-memory notification store from conftest), the API's validation / 401 / 404 /
lifecycle through the fake session from tests/test_authorization.py, and the login and
startup hooks. Everything that needs real locking, constraints or the create services
end to end is in tests/test_recurring_pg.py.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.main import app
from app.models.recurring import RecurringRule
from app.services import notifications, recurring_service
from app.services.recurring_service import (
    apply_cancel,
    apply_end_date,
    apply_pause,
    apply_resume,
    due_date,
    next_occurrence_after,
    notice_date,
    occurrence_on_or_after,
    schedule_between,
    today_in_kolkata,
)
from tests import notification_fakes
from tests.test_authorization import (  # noqa: F401 - fixtures
    auth_db,
    client_auth,
    headers_a,
    headers_b,
    token_a,
    token_b,
    user_a,
    user_b,
)

CATEGORY = "00000000-0000-4000-8000-000000000001"
D = date.fromisoformat


def ist(stamp: str) -> datetime:
    """An Asia/Kolkata wall-clock time as an aware UTC datetime."""
    return datetime.fromisoformat(stamp + "+05:30").astimezone(UTC)


def rule(
    frequency: str = "daily",
    start: str = "2024-01-02",
    end: str | None = None,
    status: str = "active",
    next_run: str | None = "default",
) -> RecurringRule:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return RecurringRule(
        id=uuid.uuid4(), owner_id=uuid.uuid4(), group_id=None, frequency=frequency,
        start_date=D(start), end_date=D(end) if end else None,
        next_run_date=D(start) if next_run == "default" else (D(next_run) if next_run else None),
        status=status, amount_paise=12345, category_id=uuid.UUID(CATEGORY), description="Rent",
        notes=None, merchant=None, payment_mode=None, split=None,
        created_at=now, updated_at=now, paused_at=None, cancelled_at=None,
    )


@pytest.fixture
def clock(monkeypatch):
    """Fake clock for recurring_service: clock['now'] is the current UTC time."""
    state = {"now": ist("2024-01-01T10:00:00")}
    monkeypatch.setattr(recurring_service, "_now", lambda: state["now"])
    return state


# ==============================================================================
# Date maths
# ==============================================================================


def test_daily_and_weekly_schedules():
    assert schedule_between(D("2024-01-30"), "daily", None, D("2024-01-30"), D("2024-02-02")) == [
        D("2024-01-30"), D("2024-01-31"), D("2024-02-01"), D("2024-02-02"),
    ]
    assert schedule_between(D("2024-01-03"), "weekly", None, D("2024-01-01"), D("2024-01-31")) == [
        D("2024-01-03"), D("2024-01-10"), D("2024-01-17"), D("2024-01-24"), D("2024-01-31"),
    ]
    # on-or-after lands on the schedule, never between two dates
    assert occurrence_on_or_after(D("2024-01-03"), "weekly", D("2024-01-04")) == D("2024-01-10")
    assert occurrence_on_or_after(D("2024-01-03"), "weekly", D("2024-01-10")) == D("2024-01-10")
    assert occurrence_on_or_after(D("2024-01-03"), "daily", D("2023-12-01")) == D("2024-01-03")


def test_monthly_on_the_31st_clamps_and_returns_to_the_31st():
    leap = schedule_between(D("2024-01-31"), "monthly", None, D("2024-01-01"), D("2024-07-31"))
    assert leap == [
        D("2024-01-31"), D("2024-02-29"), D("2024-03-31"), D("2024-04-30"),
        D("2024-05-31"), D("2024-06-30"), D("2024-07-31"),
    ]
    common = schedule_between(D("2023-01-31"), "monthly", None, D("2023-01-01"), D("2023-03-31"))
    assert common == [D("2023-01-31"), D("2023-02-28"), D("2023-03-31")]
    # 30th and 29th behave the same way; a day that exists everywhere never moves
    assert schedule_between(D("2023-01-30"), "monthly", None, D("2023-01-01"), D("2023-03-31")) == [
        D("2023-01-30"), D("2023-02-28"), D("2023-03-30"),
    ]
    assert schedule_between(D("2024-01-29"), "monthly", None, D("2024-01-01"), D("2024-03-31")) == [
        D("2024-01-29"), D("2024-02-29"), D("2024-03-29"),
    ]
    assert next_occurrence_after(D("2024-01-31"), "monthly", D("2024-02-29")) == D("2024-03-31")
    # across a year boundary
    assert next_occurrence_after(D("2024-12-31"), "monthly", D("2024-12-31")) == D("2025-01-31")


def test_yearly_and_leap_years():
    assert schedule_between(D("2024-02-29"), "yearly", None, D("2024-01-01"), D("2028-12-31")) == [
        D("2024-02-29"), D("2025-02-28"), D("2026-02-28"), D("2027-02-28"), D("2028-02-29"),
    ]
    assert next_occurrence_after(D("2024-03-15"), "yearly", D("2024-03-15")) == D("2025-03-15")
    assert occurrence_on_or_after(D("2024-03-15"), "yearly", D("2025-03-16")) == D("2026-03-15")


def test_end_date_is_inclusive_and_stops_the_schedule():
    assert schedule_between(D("2024-01-05"), "weekly", D("2024-01-19"), D("2024-01-01"), D("2024-12-31")) == [
        D("2024-01-05"), D("2024-01-12"), D("2024-01-19"),
    ]
    assert schedule_between(D("2024-01-05"), "weekly", D("2024-01-18"), D("2024-01-01"), D("2024-12-31"))[-1] == D(
        "2024-01-12"
    )


# ==============================================================================
# Asia/Kolkata and the 24-hour notice
# ==============================================================================


def test_today_is_decided_in_asia_kolkata():
    assert today_in_kolkata(datetime(2024, 1, 1, 18, 29, 59, tzinfo=UTC)) == D("2024-01-01")
    assert today_in_kolkata(datetime(2024, 1, 1, 18, 30, 0, tzinfo=UTC)) == D("2024-01-02")


def test_notice_is_due_from_24_hours_before_the_occurrence():
    r = rule(next_run="2024-01-03")
    # Occurrence due 2024-01-03 00:00 IST; notice due from 2024-01-02 00:00 IST.
    assert notice_date(r, today_in_kolkata(ist("2024-01-01T23:59:59"))) is None
    assert notice_date(r, today_in_kolkata(ist("2024-01-02T00:00:00"))) == D("2024-01-03")
    assert notice_date(r, today_in_kolkata(ist("2024-01-02T23:59:59"))) == D("2024-01-03")
    # ... and is not a "creation" yet; on the day it is due for creation instead.
    assert due_date(r, D("2024-01-02")) is None
    assert due_date(r, D("2024-01-03")) == D("2024-01-03")
    assert notice_date(r, D("2024-01-03")) is None


@pytest.mark.parametrize("state", ["paused", "cancelled"])
def test_paused_and_cancelled_rules_get_no_notice_and_no_occurrence(state):
    r = rule(status=state, next_run="2024-01-03")
    assert notice_date(r, D("2024-01-02")) is None
    assert due_date(r, D("2024-01-05")) is None


async def test_upcoming_notice_is_stored_once_per_rule_and_date():
    r = rule()
    info = recurring_service._rule_info(r)
    assert await recurring_service.send_upcoming_notice(info, D("2024-01-02")) is True
    assert await recurring_service.send_upcoming_notice(info, D("2024-01-02")) is False
    assert await recurring_service.send_upcoming_notice(info, D("2024-01-03")) is True
    stored = notification_fakes.get_emitted_notifications()
    assert [e.dedupe_key for e in stored] == [
        f"recurring_expense_upcoming:{r.id}:2024-01-02",
        f"recurring_expense_upcoming:{r.id}:2024-01-03",
    ]
    assert stored[0].kind == "recurring_expense_upcoming"
    assert stored[0].user_id == str(r.owner_id)
    assert stored[0].body == "Rent (₹123.45) will be added on 2024-01-02."


def test_skipped_notice_text():
    title, body = notifications.render_notification(
        "recurring_expense_skipped",
        {"description": "Wifi", "amount_paise": 99900, "occurrence_date": "2024-02-01",
         "reason_text": "a participant is no longer an active member of the group"},
    )
    assert title == "Recurring expense skipped"
    assert body == "Wifi (₹999) for 2024-02-01 was not added: a participant is no longer an active member of the group."


# ==============================================================================
# Pause / resume / cancel / edit (pure transitions)
# ==============================================================================


def test_pause_then_resume_does_not_back_fill_the_paused_period():
    r = rule(frequency="weekly", start="2024-01-03", next_run="2024-01-24")
    apply_pause(r, ist("2024-01-19T10:00:00"))
    assert r.status == "paused" and r.paused_at is not None
    apply_resume(r, ist("2024-02-02T10:00:00"))
    # 24 Jan and 31 Jan fell inside the pause: continue on the next date after today.
    assert r.status == "active" and r.next_run_date == D("2024-02-07") and r.paused_at is None


def test_resume_includes_a_date_scheduled_today_and_keeps_a_future_next_date():
    r = rule(start="2024-01-02", next_run="2024-01-05", status="paused")
    apply_resume(r, ist("2024-01-10T08:00:00"))
    assert r.next_run_date == D("2024-01-10")
    r2 = rule(frequency="monthly", start="2024-01-31", next_run="2024-03-31", status="paused")
    apply_resume(r2, ist("2024-03-01T08:00:00"))
    assert r2.next_run_date == D("2024-03-31")


def test_resume_after_the_end_date_has_nothing_left():
    r = rule(start="2024-01-02", end="2024-01-10", next_run="2024-01-05", status="paused")
    apply_resume(r, ist("2024-02-01T08:00:00"))
    assert r.status == "active" and r.next_run_date is None


def test_invalid_transitions_are_409_and_cancel_is_final():
    r = rule()
    with pytest.raises(HTTPException) as exc:
        apply_resume(r, ist("2024-01-02T00:00:00"))
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "RULE_NOT_PAUSED"
    apply_pause(r, ist("2024-01-02T00:00:00"))
    with pytest.raises(HTTPException) as exc:
        apply_pause(r, ist("2024-01-02T00:00:00"))
    assert exc.value.detail["code"] == "RULE_NOT_ACTIVE"
    apply_cancel(r, ist("2024-01-02T00:00:00"))
    assert r.status == "cancelled" and r.next_run_date is None and r.cancelled_at is not None
    for transition in (apply_pause, apply_resume, apply_cancel):
        with pytest.raises(HTTPException) as exc:
            transition(r, ist("2024-01-03T00:00:00"))
        assert exc.value.status_code == 409 and exc.value.detail["code"] == "RULE_CANCELLED"
    assert due_date(r, D("2030-01-01")) is None


def test_editing_the_end_date_changes_only_future_occurrences():
    r = rule(frequency="weekly", start="2024-01-05", next_run="2024-02-02")
    apply_end_date(r, D("2024-01-31"), D("2024-01-30"), last_handled=D("2024-01-26"))
    assert r.next_run_date is None  # nothing left before the new end
    # Extending an ended rule continues on/after today; dates in between are not back-filled.
    apply_end_date(r, None, D("2024-02-20"), last_handled=D("2024-01-26"))
    assert r.next_run_date == D("2024-02-23")
    with pytest.raises(HTTPException) as exc:
        apply_end_date(r, D("2024-01-01"), D("2024-02-20"), last_handled=None)
    assert exc.value.detail["code"] == "INVALID_END_DATE"


def test_handled_dates_are_never_due_again():
    """The generator only creates rule.next_run_date, which only moves forward once a date is
    handled; nothing looks at expenses, so deleting a generated expense cannot bring it back
    (verified end to end with soft and hard deletes in tests/test_recurring_pg.py)."""
    r = rule(start="2024-01-02")
    r.next_run_date = recurring_service._following(r, D("2024-01-02"))
    assert r.next_run_date == D("2024-01-03")
    assert due_date(r, D("2024-01-10")) == D("2024-01-03")
    assert all(due_date(r, d) != D("2024-01-02") for d in (D("2024-01-02"), D("2024-02-01")))


# ==============================================================================
# API through the fake session: validation, 401, 404, lifecycle
# ==============================================================================


def body(**overrides):
    data = {
        "frequency": "monthly", "startDate": "2024-01-31", "amountPaise": 150000,
        "categoryId": CATEGORY, "description": "  Rent  ",
    }
    data.update(overrides)
    return data


async def test_create_personal_rule_and_list_it(client_auth, headers_a, user_a, clock):
    resp = await client_auth.post("/api/v1/recurring", json=body(endDate="2024-12-31"), headers=headers_a)
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["status"] == "active"
    assert data["nextRunDate"] == "2024-01-31" and data["startDate"] == "2024-01-31"
    assert data["amountPaise"] == 150000 and data["description"] == "Rent"
    assert data["groupId"] is None and data["split"] is None
    listed = await client_auth.get("/api/v1/recurring?status=active", headers=headers_a)
    assert [r["id"] for r in listed.json()["data"]] == [data["id"]]
    assert listed.json()["meta"] == {"total": 1, "limit": 50, "offset": 0}


@pytest.mark.parametrize(
    "overrides",
    [
        {"amountPaise": 0},
        {"amountPaise": -5},
        {"amountPaise": 10.5},
        {"amountPaise": True},
        {"amountPaise": 9_223_372_036_854_775_808},
        {"frequency": "hourly"},
        {"startDate": "2024-02-10", "endDate": "2024-02-01"},
        {"description": "   "},
        {"description": "x" * 256},
        {"notes": "n" * 1001},
        {"split": {"splitMode": "equal"}},  # split without group
        {"ownerId": str(uuid.uuid4())},
        {"status": "paused"},
        {"nextRunDate": "2024-01-01"},
    ],
)
async def test_create_validation_errors_are_422(client_auth, headers_a, clock, overrides):
    resp = await client_auth.post("/api/v1/recurring", json=body(**overrides), headers=headers_a)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "VALIDATION_ERROR"


async def test_start_date_must_be_today_or_later_in_kolkata(client_auth, headers_a, clock):
    clock["now"] = ist("2024-01-31T00:30:00")  # still 30 Jan in UTC, already 31 Jan in Kolkata
    past = await client_auth.post("/api/v1/recurring", json=body(startDate="2024-01-30"), headers=headers_a)
    assert past.status_code == 400 and past.json()["code"] == "START_DATE_IN_PAST"
    ok = await client_auth.post("/api/v1/recurring", json=body(startDate="2024-01-31"), headers=headers_a)
    assert ok.status_code == 201
    far = await client_auth.post("/api/v1/recurring", json=body(startDate="2025-03-01"), headers=headers_a)
    assert far.status_code == 400 and far.json()["code"] == "START_DATE_TOO_FAR"


async def test_unknown_or_foreign_category_is_rejected(client_auth, headers_a, clock):
    resp = await client_auth.post("/api/v1/recurring", json=body(categoryId=str(uuid.uuid4())), headers=headers_a)
    assert resp.status_code == 400 and resp.json()["code"] == "INVALID_CATEGORY"


async def test_requests_without_a_token_are_401(client):
    rid = uuid.uuid4()
    for method, path in [
        ("POST", "/api/v1/recurring"), ("GET", "/api/v1/recurring"), ("GET", f"/api/v1/recurring/{rid}"),
        ("PATCH", f"/api/v1/recurring/{rid}"), ("POST", f"/api/v1/recurring/{rid}/pause"),
        ("POST", f"/api/v1/recurring/{rid}/resume"), ("POST", f"/api/v1/recurring/{rid}/cancel"),
        ("GET", f"/api/v1/recurring/{rid}/occurrences"),
    ]:
        resp = await client.request(method, path, json=body())
        assert resp.status_code == 401, (method, path)


async def test_another_users_rule_is_404_on_every_endpoint(client_auth, headers_a, headers_b, clock):
    rid = (await client_auth.post("/api/v1/recurring", json=body(), headers=headers_a)).json()["data"]["id"]
    for method, path, payload in [
        ("GET", f"/api/v1/recurring/{rid}", None),
        ("PATCH", f"/api/v1/recurring/{rid}", {"amountPaise": 1}),
        ("POST", f"/api/v1/recurring/{rid}/pause", None),
        ("POST", f"/api/v1/recurring/{rid}/resume", None),
        ("POST", f"/api/v1/recurring/{rid}/cancel", None),
        ("GET", f"/api/v1/recurring/{rid}/occurrences", None),
    ]:
        resp = await client_auth.request(method, path, json=payload, headers=headers_b)
        assert resp.status_code == 404 and resp.json()["code"] == "RECURRING_RULE_NOT_FOUND", (method, path)
    still = await client_auth.get(f"/api/v1/recurring/{rid}", headers=headers_a)
    assert still.json()["data"]["status"] == "active" and still.json()["data"]["amountPaise"] == 150000


async def test_lifecycle_and_edit_through_the_api(client_auth, headers_a, clock):
    rid = (await client_auth.post("/api/v1/recurring", json=body(frequency="weekly", startDate="2024-01-03"),
                                  headers=headers_a)).json()["data"]["id"]
    url = f"/api/v1/recurring/{rid}"

    edited = await client_auth.patch(url, json={"amountPaise": 99900, "notes": "new price"}, headers=headers_a)
    assert edited.status_code == 200 and edited.json()["data"]["amountPaise"] == 99900
    for bad in ({}, {"amountPaise": None}, {"frequency": "daily"}, {"startDate": "2024-02-01"},
                {"groupId": str(uuid.uuid4())}, {"amountPaise": 1.5}):
        resp = await client_auth.patch(url, json=bad, headers=headers_a)
        assert resp.status_code == 422, bad
    no_split = await client_auth.patch(url, json={"split": {"splitMode": "equal"}}, headers=headers_a)
    assert no_split.status_code == 400 and no_split.json()["code"] == "SPLIT_NOT_ALLOWED"

    clock["now"] = ist("2024-01-19T10:00:00")
    assert (await client_auth.post(f"{url}/pause", headers=headers_a)).json()["data"]["status"] == "paused"
    again = await client_auth.post(f"{url}/pause", headers=headers_a)
    assert again.status_code == 409 and again.json()["code"] == "RULE_NOT_ACTIVE"
    clock["now"] = ist("2024-02-02T10:00:00")
    resumed = (await client_auth.post(f"{url}/resume", headers=headers_a)).json()["data"]
    assert resumed["status"] == "active" and resumed["nextRunDate"] == "2024-02-07"

    cancelled = (await client_auth.post(f"{url}/cancel", headers=headers_a)).json()["data"]
    assert cancelled["status"] == "cancelled" and cancelled["nextRunDate"] is None
    for method, path, payload in [("POST", f"{url}/resume", None), ("POST", f"{url}/pause", None),
                                  ("POST", f"{url}/cancel", None), ("PATCH", url, {"amountPaise": 5})]:
        resp = await client_auth.request(method, path, json=payload, headers=headers_a)
        assert resp.status_code == 409 and resp.json()["code"] == "RULE_CANCELLED", (method, path)


async def test_idempotency_key_replays_the_same_rule(client_auth, headers_a, clock):
    first = await client_auth.post("/api/v1/recurring", json=body(), headers={**headers_a, "Idempotency-Key": "k-1"})
    again = await client_auth.post("/api/v1/recurring", json=body(), headers={**headers_a, "Idempotency-Key": "k-1"})
    assert first.status_code == 201 and again.status_code == 201
    assert again.headers.get("X-Idempotent-Replay") == "true"
    assert again.json()["data"]["id"] == first.json()["data"]["id"]
    other = await client_auth.post(
        "/api/v1/recurring", json=body(amountPaise=1), headers={**headers_a, "Idempotency-Key": "k-1"}
    )
    assert other.status_code == 409 and other.json()["code"] == "IDEMPOTENCY_CONFLICT"
    listed = await client_auth.get("/api/v1/recurring", headers=headers_a)
    assert listed.json()["meta"]["total"] == 1


# ==============================================================================
# Login catch-up and the background task
# ==============================================================================


LOGIN = {"email": "user_a@example.com", "password": "PasswordA123!"}


async def test_login_runs_the_catch_up_for_that_user(client_auth, user_a, monkeypatch):
    seen: list[uuid.UUID | None] = []

    async def fake_run_due(*, user_id=None, now=None):
        seen.append(user_id)
        return recurring_service.RunStats()

    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_ENABLED", True)
    monkeypatch.setattr(recurring_service, "run_due", fake_run_due)
    resp = await client_auth.post("/api/v1/auth/login", json=LOGIN)
    assert resp.status_code == 200 and seen == [user_a.id]


async def test_failed_login_does_not_run_the_catch_up(client_auth, user_a, monkeypatch):
    called = False

    async def fake_run_due(**_):
        nonlocal called
        called = True

    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_ENABLED", True)
    monkeypatch.setattr(recurring_service, "run_due", fake_run_due)
    resp = await client_auth.post("/api/v1/auth/login", json={**LOGIN, "password": "WrongPassword999!"})
    assert resp.status_code == 401 and called is False


async def test_catch_up_failure_still_logs_in(client_auth, user_a, monkeypatch, caplog):
    async def broken(**_):
        raise RuntimeError("generator exploded")

    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_ENABLED", True)
    monkeypatch.setattr(recurring_service, "run_due", broken)
    resp = await client_auth.post("/api/v1/auth/login", json=LOGIN)
    assert resp.status_code == 200 and "tokens" in resp.json()
    assert any("Login catch-up failed" in r.getMessage() for r in caplog.records)


async def test_catch_up_timeout_still_logs_in_quickly(client_auth, user_a, monkeypatch, caplog):
    cancelled = asyncio.Event()

    async def slow(**_):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "RECURRING_LOGIN_CATCHUP_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(recurring_service, "run_due", slow)
    started = time.monotonic()
    resp = await client_auth.post("/api/v1/auth/login", json=LOGIN)
    elapsed = time.monotonic() - started
    assert resp.status_code == 200 and "tokens" in resp.json()
    assert elapsed < 5, elapsed  # bounded by the time limit, never the 30 s run
    assert cancelled.is_set()  # the cut-off run was cancelled (its open transaction rolls back)
    assert any("timed out" in r.getMessage() for r in caplog.records)


def test_login_catch_up_settings_have_safe_defaults():
    defaults = type(settings).model_fields
    assert defaults["RECURRING_LOGIN_CATCHUP_TIMEOUT_SECONDS"].default == 3.0
    assert defaults["RECURRING_RUN_INTERVAL_SECONDS"].default == 3600
    assert defaults["RECURRING_MAX_OCCURRENCES_PER_RULE_PER_RUN"].default == 100
    assert defaults["RECURRING_SCHEDULER_ENABLED"].default is True


async def test_scheduler_runs_at_start_keeps_going_after_errors_and_stops_cleanly(monkeypatch):
    calls = 0

    async def flaky(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first run fails")
        return recurring_service.RunStats()

    monkeypatch.setattr(recurring_service, "run_due", flaky)
    task = recurring_service.start_scheduler(interval_seconds=0.01)
    for _ in range(200):
        if calls >= 3:
            break
        await asyncio.sleep(0.01)
    assert calls >= 3  # first (startup) run failed, the loop carried on
    await recurring_service.stop_scheduler(task)
    assert task.done() and task.cancelled()


async def test_lifespan_starts_the_task_without_waiting_and_cancels_it_on_shutdown(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def never_finishes(**_):
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def no_history() -> int:
        return 0

    import app.main as main_module

    monkeypatch.setattr(main_module, "restore_user_history", no_history)
    monkeypatch.setattr(recurring_service, "run_due", never_finishes)
    monkeypatch.setattr(settings, "RECURRING_SCHEDULER_ENABLED", True)
    async with asyncio.timeout(5):  # startup must not wait for the (endless) catch-up
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(started.wait(), 2)
            assert not cancelled.is_set()
    assert cancelled.is_set()


async def test_lifespan_with_the_scheduler_disabled_starts_nothing(monkeypatch):
    async def no_history() -> int:
        return 0

    def must_not_start(*_a, **_k):
        raise AssertionError("scheduler started although disabled")

    import app.main as main_module

    monkeypatch.setattr(main_module, "restore_user_history", no_history)
    monkeypatch.setattr(recurring_service, "start_scheduler", must_not_start)
    async with app.router.lifespan_context(app):
        pass
