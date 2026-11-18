"""Balances and settlements schemas (US-20 / T-32).

These schemas serialise in snake_case (plain BaseModel, not BaseSchema)
because mobile/src/features/balances/services/balancesApi.ts reads
snake_case fields such as `created_at` and `updated_at` without a camelCase
fallback. All money fields are whole paise (int).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SettlementBaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
    )


class SettlementCreateRequest(SettlementBaseSchema):
    """Payload to record a full or partial settlement between two group members."""

    model_config = ConfigDict(extra="forbid")

    payer_id: uuid.UUID = Field(
        ..., description="UUID of the member making the repayment (debtor)."
    )
    payee_id: uuid.UUID = Field(
        ..., description="UUID of the member receiving the repayment (creditor)."
    )
    amount_paise: int | None = Field(
        None,
        gt=0,
        le=9_223_372_036_854_775_807,
        description=(
            "Repayment amount in positive integer paise. Required unless "
            "is_full_settlement is true."
        ),
    )
    is_full_settlement: bool = Field(
        False,
        description=(
            "Settle everything the payer currently owes the payee. If amount_paise "
            "is also given it must equal that outstanding amount."
        ),
    )
    payment_method: str | None = Field(
        None, max_length=50, description="Payment channel (e.g. upi, cash, bank_transfer)."
    )
    notes: str | None = Field(
        None, max_length=1000, description="Optional notes about the settlement."
    )
    settlement_date: date | None = Field(
        None, description="Date of repayment (YYYY-MM-DD). Defaults to today in Asia/Kolkata."
    )
    @field_validator("amount_paise", mode="before")
    @classmethod
    def reject_non_integer_money(cls, val: Any) -> Any:
        if isinstance(val, bool):
            raise ValueError("amount_paise cannot be a boolean.")
        if isinstance(val, float):
            raise ValueError("Floating-point money values are not allowed. Provide integer paise.")
        return val


class SettlementResponse(SettlementBaseSchema):
    """A recorded settlement."""

    id: uuid.UUID
    group_id: uuid.UUID
    payer_id: uuid.UUID
    payee_id: uuid.UUID
    amount_paise: int
    status: str
    payment_method: str | None = None
    notes: str | None = None
    settlement_date: date
    is_partial: bool = False
    remaining_debt_paise: int | None = Field(
        None,
        description=(
            "What the payer still owed the payee right after this settlement "
            "(only set on the create response)."
        ),
    )
    created_at: datetime
    updated_at: datetime


class MemberBalanceItem(SettlementBaseSchema):
    """Net position for one group member."""

    user_id: uuid.UUID
    net_balance_paise: int = Field(
        ..., description="> 0: others owe this member; < 0: this member owes others."
    )
    owes_paise: int
    receives_paise: int
    status: Literal["creditor", "debtor", "settled"]


class TransferItem(SettlementBaseSchema):
    """Suggested repayment produced by ledger.simplify()."""

    from_user: str
    to_user: str
    amount_paise: int


class GroupBalancesResponse(SettlementBaseSchema):
    """Balances for a group, from ledger.net_positions() and ledger.simplify().

    Keeps the original `group_id`, `net_positions` and `suggested_transfers`
    keys of this endpoint and adds `members`, `total_debt_paise` and `currency`.
    """

    group_id: uuid.UUID
    net_positions: dict[str, int]
    suggested_transfers: list[TransferItem]
    members: list[MemberBalanceItem]
    total_debt_paise: int = Field(
        ..., description="Sum of all creditors' positions (equals the sum owed by debtors)."
    )
    currency: str = "INR"


class SimplifiedRepaymentsResponse(SettlementBaseSchema):
    """Greedy simplified repayment suggestions (ledger.simplify())."""

    group_id: uuid.UUID
    suggested_transfers: list[TransferItem]
    total_transfers: int
    total_amount_paise: int
