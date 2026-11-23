"""Fast tests for budgets (US-25 / T-48): no database.

Pure period windows (Monday weeks and calendar months in Asia/Kolkata, including the IST
midnight boundary), the integer threshold maths and status labels at 79/80/99/100/150%,
which alert rows a spending level records, the notification text, and the API's
validation / 401 / 404 / duplicate rules through the fake session from
tests/test_authorization.py. Real alerts, the UNIQUE keys, concurrency and the expense
hooks end to end are in tests/test_budgets_pg.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from app.models.budget import Budget
from app.models.category import Category
from app.models.expense import Expense
from app.schemas.budget import BudgetCreate, BudgetUpdate
from app.services import budget_service, notifications
from app.services.budget_service import (
    alerts_to_record,
    build_progress,
    dedupe_key,
    period_bounds,
    reached_thresholds,
    status_for,
    today_in_kolkata,
)
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
OTHER_CATEGORY = "00000000-0000-4000-8000-000000000002"
D = date.fromisoformat


def ist(stamp: str) -> datetime:
    """An Asia/Kolkata wall-clock time as an aware UTC datetime."""
    return datetime.fromisoformat(stamp + "+05:30").astimezone(UTC)


@pytest.fixture
def clock(monkeypatch):
    """Fake clock for budget_service: clock['now'] is the current UTC time."""
    state = {"now": ist("2025-03-05T12:00:00")}  # a Wednesday
    monkeypatch.setattr(budget_service, "_now", lambda: state["now"])
    return state


def expense(owner: uuid.UUID, amount: int, day: str, category: str = CATEGORY, deleted: bool = False) -> Expense:
    now = datetime.now(UTC)
    return Expense(
        id=uuid.uuid4(), user_id=owner, group_id=None, category_id=uuid.UUID(category),
        amount_minor=amount, description="Groceries", expense_date=D(day), version=1,
        created_at=now, updated_at=now, deleted_at=now if deleted else None,
    )


# ==============================================================================
# Period windows (Asia/Kolkata)
# ==============================================================================


def test_weekly_period_is_monday_to_sunday():
    for day in ("2025-03-03", "2025-03-05", "2025-03-09"):  # Monday, Wednesday, Sunday
        assert period_bounds("weekly", D(day)) == (D("2025-03-03"), D("2025-03-09"))
    assert period_bounds("weekly", D("2025-03-10")) == (D("2025-03-10"), D("2025-03-16"))
    # a week that crosses a month and a year boundary
    assert period_bounds("weekly", D("2025-01-01")) == (D("2024-12-30"), D("2025-01-05"))


def test_monthly_period_is_the_calendar_month():
    assert period_bounds("monthly", D("2025-03-01")) == (D("2025-03-01"), D("2025-03-31"))
    assert period_bounds("monthly", D("2025-03-31")) == (D("2025-03-01"), D("2025-03-31"))
    assert period_bounds("monthly", D("2024-02-15")) == (D("2024-02-01"), D("2024-02-29"))  # leap year
    assert period_bounds("monthly", D("2025-02-15")) == (D("2025-02-01"), D("2025-02-28"))
    assert period_bounds("monthly", D("2025-04-30")) == (D("2025-04-01"), D("2025-04-30"))
    assert period_bounds("monthly", D("2024-12-31")) == (D("2024-12-01"), D("2024-12-31"))


def test_today_is_decided_in_asia_kolkata_at_the_ist_midnight_boundary():
    # Sunday 23:59:59 IST is 18:29:59 UTC: still the old week and the old month.
    sunday_night = datetime(2025, 3, 9, 18, 29, 59, tzinfo=UTC)
    assert today_in_kolkata(sunday_night) == D("2025-03-09")
    assert period_bounds("weekly", today_in_kolkata(sunday_night)) == (D("2025-03-03"), D("2025-03-09"))
    # One second later it is Monday 00:00 IST although it is still Sunday in UTC.
    monday = datetime(2025, 3, 9, 18, 30, 0, tzinfo=UTC)
    assert monday.date() == D("2025-03-09")
    assert today_in_kolkata(monday) == D("2025-03-10")
    assert period_bounds("weekly", today_in_kolkata(monday)) == (D("2025-03-10"), D("2025-03-16"))
    # Month: 31 March 23:59:59 IST vs 1 April 00:00 IST.
    assert period_bounds("monthly", today_in_kolkata(datetime(2025, 3, 31, 18, 29, 59, tzinfo=UTC)))[0] == D("2025-03-01")
    assert period_bounds("monthly", today_in_kolkata(datetime(2025, 3, 31, 18, 30, 0, tzinfo=UTC)))[0] == D("2025-04-01")


# ==============================================================================
# Threshold maths and status labels (integers only)
# ==============================================================================


@pytest.mark.parametrize(
    ("spent", "limit", "percent", "reached", "label"),
    [
        (0, 10_000, 0, (), "under"),
        (7_900, 10_000, 79, (), "under"),
        (7_999, 10_000, 79, (), "under"),  # 79.99% is still under
        (8_000, 10_000, 80, (80,), "warning"),
        (9_900, 10_000, 99, (80,), "warning"),
        (9_999, 10_000, 99, (80,), "warning"),
        (10_000, 10_000, 100, (80, 100), "exceeded"),
        (15_000, 10_000, 150, (80, 100), "exceeded"),
        # limits that do not divide evenly: no rounding up
        (2, 3, 66, (), "under"),
        (3, 3, 100, (80, 100), "exceeded"),
        (6, 7, 85, (80,), "warning"),
        (5, 7, 71, (), "under"),
        (79, 99, 79, (), "under"),  # 79.79%
        (80, 100, 80, (80,), "warning"),
        # a very large limit stays exact
        (8 * 10**17, 10**18, 80, (80,), "warning"),
        (8 * 10**17 - 1, 10**18, 79, (), "under"),
    ],
)
def test_threshold_maths_and_status(spent, limit, percent, reached, label):
    assert reached_thresholds(spent, limit) == reached
    assert status_for(spent, limit) == label
    progress = build_progress(spent, limit, D("2025-03-01"), D("2025-03-31"))
    assert progress.percent_used == percent
    assert progress.status == label
    assert progress.spent_paise == spent
    assert progress.remaining_paise == limit - spent
    assert progress.over_by_paise == max(spent - limit, 0)


def test_over_the_limit_reports_negative_remaining_and_over_by():
    progress = build_progress(15_000, 10_000, D("2025-03-03"), D("2025-03-09"))
    assert progress.remaining_paise == -5_000
    assert progress.over_by_paise == 5_000
    assert (progress.period_start, progress.period_end) == (D("2025-03-03"), D("2025-03-09"))


def test_alert_rows_recorded_for_each_spending_level():
    assert alerts_to_record(7_900, 10_000) == []  # 79%: nothing
    assert alerts_to_record(8_000, 10_000) == [(80, False)]  # 80%: the 80% alert
    assert alerts_to_record(9_999, 10_000) == [(80, False)]
    # 100% and beyond: the 80% row is suppressed, so only the 100% alert can be announced
    assert alerts_to_record(10_000, 10_000) == [(80, True), (100, False)]
    assert alerts_to_record(15_000, 10_000) == [(80, True), (100, False)]


def test_dedupe_key_names_the_budget_period_and_threshold():
    budget_id = uuid.UUID("12345678-1234-4234-8234-123456789abc")
    assert dedupe_key(budget_id, D("2025-03-01"), 80) == (
        "budget_threshold:12345678-1234-4234-8234-123456789abc:2025-03-01:80"
    )


def test_budget_notifications_render_a_title_and_body():
    payload = {"period": "weekly", "category_name": "Groceries", "spent_paise": 850_000,
               "limit_paise": 1_000_000, "percent_used": 85}
    assert notifications.render_notification("budget_warning", payload) == (
        "Budget at 80%", "You have used 85% of your weekly Groceries budget (₹8,500 of ₹10,000)."
    )
    title, body = notifications.render_notification(
        "budget_exceeded", {"period": "monthly", "spent_paise": 1_200_050, "limit_paise": 1_000_000, "percent_used": 120}
    )
    assert title == "Budget exceeded"
    assert body == "You have used 120% of your monthly overall budget (₹12,000.50 of ₹10,000)."


# ==============================================================================
# Schemas
# ==============================================================================


@pytest.mark.parametrize(
    "body",
    [
        {"period": "daily", "limitPaise": 100},
        {"period": "yearly", "limitPaise": 100},
        {"period": "weekly", "limitPaise": 0},
        {"period": "weekly", "limitPaise": -5},
        {"period": "weekly", "limitPaise": 100.5},
        {"period": "weekly", "limitPaise": 100.0},
        {"period": "weekly", "limitPaise": True},
        {"period": "weekly", "limitPaise": "abc"},
        {"period": "weekly", "limitPaise": 9_223_372_036_854_775_808},
        {"period": "weekly"},
        {"limitPaise": 100},
        {"period": "weekly", "limitPaise": 100, "categoryId": "not-a-uuid"},
        {"period": "weekly", "limitPaise": 100, "spentPaise": 0},
    ],
)
def test_create_schema_rejects_bad_input(body):
    with pytest.raises(ValueError):
        BudgetCreate.model_validate(body)


def test_create_schema_accepts_snake_and_camel_case():
    a = BudgetCreate.model_validate({"period": "weekly", "limitPaise": 100})
    b = BudgetCreate.model_validate({"period": "monthly", "limit_paise": 250, "category_id": CATEGORY})
    assert (a.period, a.limit_paise, a.category_id) == ("weekly", 100, None)
    assert (b.period, b.limit_paise, str(b.category_id)) == ("monthly", 250, CATEGORY)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"limitPaise": None},
        {"limitPaise": 0},
        {"limitPaise": 1.5},
        {"limitPaise": 100, "period": "weekly"},
        {"limitPaise": 100, "categoryId": CATEGORY},
    ],
)
def test_update_schema_allows_only_a_positive_limit(body):
    with pytest.raises(ValueError):
        BudgetUpdate.model_validate(body)


# ==============================================================================
# API through the fake session
# ==============================================================================


async def test_every_budget_endpoint_needs_authentication(client_auth):
    some_id = uuid.uuid4()
    for method, path, body in [
        ("GET", "/api/v1/budgets", None),
        ("POST", "/api/v1/budgets", {"period": "weekly", "limitPaise": 100}),
        ("GET", f"/api/v1/budgets/{some_id}", None),
        ("PATCH", f"/api/v1/budgets/{some_id}", {"limitPaise": 100}),
        ("DELETE", f"/api/v1/budgets/{some_id}", None),
    ]:
        resp = await client_auth.request(method, path, json=body)
        assert resp.status_code == 401, (method, path)
        assert resp.json()["code"] in ("UNAUTHORIZED", "INVALID_TOKEN")


async def test_create_list_get_patch_delete_with_progress(client_auth, headers_a, user_a, auth_db, clock, budget_checks_recorded):
    # 7,900 of 10,000 this week (Monday 3 March to Sunday 9 March 2025), plus rows that must not count.
    for e in (
        expense(user_a.id, 5_000, "2025-03-03"),
        expense(user_a.id, 2_900, "2025-03-09"),
        expense(user_a.id, 9_999, "2025-03-02"),  # previous week
        expense(user_a.id, 9_999, "2025-03-10"),  # next week
        expense(user_a.id, 9_999, "2025-03-05", deleted=True),
    ):
        auth_db.expenses[e.id] = e

    created = await client_auth.post("/api/v1/budgets", json={"period": "weekly", "limitPaise": 10_000}, headers=headers_a)
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    assert data["period"] == "weekly" and data["categoryId"] is None and data["limitPaise"] == 10_000
    assert data["progress"] == {
        "periodStart": "2025-03-03", "periodEnd": "2025-03-09", "spentPaise": 7_900,
        "remainingPaise": 2_100, "overByPaise": 0, "percentUsed": 79, "status": "under",
    }
    assert budget_checks_recorded == [[str(user_a.id)]]  # checked after the commit

    budget_id = data["id"]
    listed = await client_auth.get("/api/v1/budgets", headers=headers_a)
    assert listed.status_code == 200
    assert listed.json()["meta"] == {"total": 1, "limit": 50, "offset": 0}
    assert listed.json()["data"][0]["progress"]["spentPaise"] == 7_900

    # Lowering the limit: progress moves at once and the threshold check runs again.
    lowered = await client_auth.patch(f"/api/v1/budgets/{budget_id}", json={"limitPaise": 7_900}, headers=headers_a)
    assert lowered.status_code == 200
    assert lowered.json()["data"]["progress"]["status"] == "exceeded"
    assert lowered.json()["data"]["progress"]["percentUsed"] == 100
    assert budget_checks_recorded == [[str(user_a.id)], [str(user_a.id)]]

    got = await client_auth.get(f"/api/v1/budgets/{budget_id}", headers=headers_a)
    assert got.status_code == 200 and got.json()["data"]["limitPaise"] == 7_900

    deleted = await client_auth.delete(f"/api/v1/budgets/{budget_id}", headers=headers_a)
    assert deleted.status_code == 204 and deleted.content == b""
    assert (await client_auth.get(f"/api/v1/budgets/{budget_id}", headers=headers_a)).status_code == 404
    assert (await client_auth.get("/api/v1/budgets", headers=headers_a)).json()["meta"]["total"] == 0


async def test_category_budget_counts_only_that_category(client_auth, headers_a, user_a, auth_db, clock):
    for e in (expense(user_a.id, 8_000, "2025-03-04"), expense(user_a.id, 5_000, "2025-03-04", OTHER_CATEGORY)):
        auth_db.expenses[e.id] = e
    food = await client_auth.post(
        "/api/v1/budgets", json={"period": "monthly", "limitPaise": 10_000, "categoryId": CATEGORY}, headers=headers_a
    )
    overall = await client_auth.post("/api/v1/budgets", json={"period": "monthly", "limitPaise": 10_000}, headers=headers_a)
    assert food.json()["data"]["progress"]["spentPaise"] == 8_000
    assert food.json()["data"]["progress"]["status"] == "warning"
    assert overall.json()["data"]["progress"]["spentPaise"] == 13_000
    assert overall.json()["data"]["progress"]["overByPaise"] == 3_000
    assert overall.json()["data"]["progress"]["periodStart"] == "2025-03-01"
    assert overall.json()["data"]["progress"]["periodEnd"] == "2025-03-31"


async def test_duplicate_active_budget_is_rejected(client_auth, headers_a, headers_b, auth_db, clock):
    first = await client_auth.post("/api/v1/budgets", json={"period": "weekly", "limitPaise": 100}, headers=headers_a)
    assert first.status_code == 201
    again = await client_auth.post("/api/v1/budgets", json={"period": "weekly", "limitPaise": 999}, headers=headers_a)
    assert again.status_code == 409 and again.json()["code"] == "BUDGET_EXISTS"

    # A different period, a category budget, or another user is not a duplicate.
    for body, headers in [
        ({"period": "monthly", "limitPaise": 100}, headers_a),
        ({"period": "weekly", "limitPaise": 100, "categoryId": CATEGORY}, headers_a),
        ({"period": "weekly", "limitPaise": 100}, headers_b),
    ]:
        assert (await client_auth.post("/api/v1/budgets", json=body, headers=headers)).status_code == 201
    category_again = await client_auth.post(
        "/api/v1/budgets", json={"period": "weekly", "limitPaise": 5, "categoryId": CATEGORY}, headers=headers_a
    )
    assert category_again.status_code == 409

    # After a delete the slot is free again.
    assert (await client_auth.delete(f"/api/v1/budgets/{first.json()['data']['id']}", headers=headers_a)).status_code == 204
    assert (await client_auth.post("/api/v1/budgets", json={"period": "weekly", "limitPaise": 7}, headers=headers_a)).status_code == 201
    assert len(auth_db.budgets) == 5
    assert len([b for b in auth_db.budgets.values() if b.deleted_at is None]) == 4


async def test_category_must_be_default_or_own(client_auth, headers_a, user_b, auth_db, clock):
    private = Category(id=uuid.uuid4(), name="B's hobby", is_default=False, owner_id=user_b.id, created_at=datetime.now(UTC))
    auth_db.categories[private.id] = private
    for category_id in (str(private.id), str(uuid.uuid4())):
        resp = await client_auth.post(
            "/api/v1/budgets", json={"period": "weekly", "limitPaise": 100, "categoryId": category_id}, headers=headers_a
        )
        assert resp.status_code == 400 and resp.json()["code"] == "INVALID_CATEGORY"
    assert auth_db.budgets == {}


async def test_api_validation_errors_use_the_error_envelope(client_auth, headers_a, user_a, auth_db, clock):
    for body in (
        {"period": "daily", "limitPaise": 100},
        {"period": "weekly", "limitPaise": 0},
        {"period": "weekly", "limitPaise": 12.5},
        {"period": "weekly", "limitPaise": 100, "userId": str(user_a.id)},
    ):
        resp = await client_auth.post("/api/v1/budgets", json=body, headers=headers_a)
        assert resp.status_code == 422, body
        assert resp.json()["code"] == "VALIDATION_ERROR"
    budget = Budget(id=uuid.uuid4(), user_id=user_a.id, period="weekly", category_id=None, limit_paise=100,
                    created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None)
    auth_db.budgets[budget.id] = budget
    for body in ({"period": "monthly", "limitPaise": 100}, {"categoryId": CATEGORY}, {}):
        resp = await client_auth.patch(f"/api/v1/budgets/{budget.id}", json=body, headers=headers_a)
        assert resp.status_code == 422, body
    assert budget.period == "weekly" and budget.category_id is None and budget.limit_paise == 100
    paging = await client_auth.get("/api/v1/budgets?limit=0", headers=headers_a)
    assert paging.status_code == 422


async def test_another_users_budget_is_404(client_auth, headers_a, headers_b, user_a, auth_db, clock):
    budget = Budget(id=uuid.uuid4(), user_id=user_a.id, period="monthly", category_id=None, limit_paise=4_200,
                    created_at=datetime.now(UTC), updated_at=datetime.now(UTC), deleted_at=None)
    auth_db.budgets[budget.id] = budget
    for method, body in (("GET", None), ("PATCH", {"limitPaise": 1}), ("DELETE", None)):
        resp = await client_auth.request(method, f"/api/v1/budgets/{budget.id}", json=body, headers=headers_b)
        assert resp.status_code == 404 and resp.json()["code"] == "BUDGET_NOT_FOUND"
    assert budget.limit_paise == 4_200 and budget.deleted_at is None


async def test_idempotency_key_replays_the_same_budget(client_auth, headers_a, auth_db, clock):
    body = {"period": "monthly", "limitPaise": 50_000}
    headers = {**headers_a, "Idempotency-Key": "budget-1"}
    first = await client_auth.post("/api/v1/budgets", json=body, headers=headers)
    replay = await client_auth.post("/api/v1/budgets", json=body, headers=headers)
    assert first.status_code == replay.status_code == 201
    assert replay.headers.get("X-Idempotent-Replay") == "true"
    assert replay.json()["data"]["id"] == first.json()["data"]["id"]
    assert len(auth_db.budgets) == 1
    conflict = await client_auth.post("/api/v1/budgets", json={**body, "limitPaise": 1}, headers=headers)
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"


# ==============================================================================
# The post-commit check never breaks a save
# ==============================================================================


async def test_check_after_commit_logs_and_swallows_failures(monkeypatch, caplog):
    async def broken(_user_ids):
        raise RuntimeError("database down")

    monkeypatch.setattr(budget_service, "_check_users", broken)
    with caplog.at_level("ERROR", logger="app.budgets"):
        await budget_service.check_after_commit([uuid.uuid4()])  # does not raise
    assert "Budget check failed; the saved record is kept (RuntimeError)" in caplog.text
    assert "database down" not in caplog.text


async def test_check_after_commit_dedupes_and_skips_invalid_ids(budget_checks_recorded):
    a, b = uuid.uuid4(), uuid.uuid4()
    await budget_service.check_after_commit([a, str(a), "not-a-uuid", b, None])  # type: ignore[list-item]
    assert budget_checks_recorded == [sorted([str(a), str(b)])]
    await budget_service.check_after_commit([])
    assert len(budget_checks_recorded) == 1  # nothing to check, nothing run


async def test_a_failing_check_does_not_fail_an_expense_save(client_auth, headers_a, user_a, auth_db, monkeypatch):
    async def broken(_user_ids):
        raise RuntimeError("budget store unavailable")

    monkeypatch.setattr(budget_service, "_check_users", broken)
    resp = await client_auth.post(
        "/api/v1/expenses",
        json={"amount_minor": 1_000, "description": "Lunch", "category_id": CATEGORY},
        headers=headers_a,
    )
    assert resp.status_code == 201
    assert len(auth_db.expenses) == 1
