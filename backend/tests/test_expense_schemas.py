import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.expense import (
    ExpenseCreate,
    ExpenseResponse,
    ExpenseUpdate,
    validate_expense_date_not_future,
    validate_paise_amount,
)


def test_validate_paise_amount_valid():
    assert validate_paise_amount(1) == 1
    assert validate_paise_amount(25000) == 25000
    assert validate_paise_amount("5000") == 5000


def test_validate_paise_amount_rejects_bool():
    with pytest.raises(ValueError, match="cannot be a boolean"):
        validate_paise_amount(True)
    with pytest.raises(ValueError, match="cannot be a boolean"):
        validate_paise_amount(False)


def test_validate_paise_amount_rejects_float():
    with pytest.raises(ValueError, match="Floating-point money values are not allowed"):
        validate_paise_amount(250.50)
    with pytest.raises(ValueError, match="Floating-point money values are not allowed"):
        validate_paise_amount(100.0)


def test_validate_paise_amount_rejects_zero_and_negative():
    with pytest.raises(ValueError, match="strictly greater than zero"):
        validate_paise_amount(0)
    with pytest.raises(ValueError, match="strictly greater than zero"):
        validate_paise_amount(-100)


def test_validate_expense_date():
    today = datetime.now(UTC).date()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    yesterday = today - timedelta(days=1)

    assert validate_expense_date_not_future(today) == today
    assert validate_expense_date_not_future(tomorrow) == tomorrow
    assert validate_expense_date_not_future(yesterday) == yesterday

    with pytest.raises(ValueError, match="cannot be later than tomorrow"):
        validate_expense_date_not_future(day_after)


def test_expense_create_valid_amount_minor():
    cat_id = uuid.uuid4()
    exp = ExpenseCreate(
        amount_minor=15000,
        description="Coffee with client",
        category_id=cat_id,
    )
    assert exp.amount_minor == 15000
    assert exp.amount_paise == 15000
    assert exp.description == "Coffee with client"
    assert exp.category_id == cat_id
    assert exp.expense_date == datetime.now(UTC).date()
    assert exp.occurred_on == exp.expense_date


def test_expense_create_valid_amount_paise_alias():
    cat_id = uuid.uuid4()
    exp = ExpenseCreate(
        amount_paise=29900,
        description="Book purchase",
        category_id=cat_id,
        occurred_on=date(2026, 10, 20),
    )
    assert exp.amount_minor == 29900
    assert exp.amount_paise == 29900
    assert exp.expense_date == date(2026, 10, 20)
    assert exp.occurred_on == date(2026, 10, 20)


def test_expense_create_rejects_zero_and_negative():
    cat_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        ExpenseCreate(
            amount_minor=0,
            description="Free item",
            category_id=cat_id,
        )
    with pytest.raises(ValidationError):
        ExpenseCreate(
            amount_minor=-500,
            description="Negative item",
            category_id=cat_id,
        )


def test_expense_create_rejects_empty_description():
    cat_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        ExpenseCreate(
            amount_minor=1000,
            description="   ",
            category_id=cat_id,
        )


def test_expense_create_rejects_future_date():
    cat_id = uuid.uuid4()
    future_date = datetime.now(UTC).date() + timedelta(days=5)
    with pytest.raises(ValidationError):
        ExpenseCreate(
            amount_minor=1000,
            description="Lunch",
            category_id=cat_id,
            expense_date=future_date,
        )


def test_expense_update_partial():
    update_data = ExpenseUpdate(
        description="Updated lunch",
        amount_minor=20000,
        version=1,
    )
    assert update_data.description == "Updated lunch"
    assert update_data.amount_minor == 20000
    assert update_data.amount_paise == 20000
    assert update_data.category_id is None
    assert update_data.version == 1


def test_expense_response_serialization():
    exp_id = uuid.uuid4()
    u_id = uuid.uuid4()
    c_id = uuid.uuid4()
    now = datetime.now(UTC)
    today = now.date()

    resp = ExpenseResponse(
        id=exp_id,
        user_id=u_id,
        category_id=c_id,
        amount_minor=35000,
        amount_paise=35000,
        description="Dinner",
        expense_date=today,
        occurred_on=today,
        notes="Card payment",
        merchant="Italian Bistro",
        payment_mode="card",
        receipt_id=None,
        version=1,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )

    dumped = resp.model_dump(by_alias=True)
    assert dumped["id"] == exp_id
    assert dumped["userId"] == u_id
    assert dumped["categoryId"] == c_id
    assert dumped["amountMinor"] == 35000
    assert dumped["amountPaise"] == 35000
    assert dumped["expenseDate"] == today
    assert dumped["occurredOn"] == today
    assert dumped["paymentMode"] == "card"
    assert dumped["merchant"] == "Italian Bistro"
    assert dumped["version"] == 1
