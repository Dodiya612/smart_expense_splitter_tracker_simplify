from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettlementBaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
    )


class SettlementCreateRequest(SettlementBaseSchema):
    """Payload to record a full or partial debt settlement."""

    payer_id: uuid.UUID | None = Field(
        None, description="UUID of the debtor member making the repayment."
    )
    payee_id: uuid.UUID | None = Field(
        None, description="UUID of the creditor member receiving the repayment."
    )
    from_user_id: uuid.UUID | None = Field(None, description="Alias for payer_id.")
    to_user_id: uuid.UUID | None = Field(None, description="Alias for payee_id.")
    amount_paise: int | None = Field(
        None, description="Repayment amount in positive integer paise."
    )
    is_full_settlement: bool = Field(
        False,
        description="Whether to settle the full remaining outstanding balance between payer and payee.",
    )
    payment_method: str | None = Field(
        None, max_length=50, description="Payment channel (e.g. upi, cash, bank_transfer)."
    )
    notes: str | None = Field(
        None, max_length=1000, description="Optional notes regarding the settlement."
    )
    settlement_date: date | None = Field(
        None, description="Date of repayment. Defaults to current UTC date."
    )

    @model_validator(mode="before")
    @classmethod
    def reconcile_aliases(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        if "payer_id" not in values:
            if "from_user_id" in values:
                values["payer_id"] = values["from_user_id"]
            elif "from_user" in values:
                values["payer_id"] = values["from_user"]
            elif "debtor_id" in values:
                values["payer_id"] = values["debtor_id"]

        if "payee_id" not in values:
            if "to_user_id" in values:
                values["payee_id"] = values["to_user_id"]
            elif "to_user" in values:
                values["payee_id"] = values["to_user"]
            elif "creditor_id" in values:
                values["payee_id"] = values["creditor_id"]

        return values

    @model_validator(mode="after")
    def validate_participants_and_amount(self) -> SettlementCreateRequest:
        if not self.payer_id or not self.payee_id:
            raise ValueError("Both payer_id and payee_id are required.")
        if self.payer_id == self.payee_id:
            raise ValueError("Payer and payee cannot be the same member.")

        if not self.is_full_settlement:
            if self.amount_paise is None:
                raise ValueError(
                    "amount_paise is required unless is_full_settlement is true."
                )
            if self.amount_paise <= 0:
                raise ValueError("amount_paise must be strictly greater than zero.")
        elif self.amount_paise is not None and self.amount_paise <= 0:
            raise ValueError("amount_paise must be strictly greater than zero.")

        return self


class SettlementResponse(SettlementBaseSchema):
    """Details of a recorded settlement."""

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
    remaining_debt_paise: int | None = None
    created_at: datetime
    updated_at: datetime


class MemberBalanceItem(SettlementBaseSchema):
    """Net financial position for a single group member."""

    user_id: uuid.UUID
    net_balance_paise: int
    owes_paise: int
    receives_paise: int
    status: str  # "creditor", "debtor", "settled"


class DebtorCreditorSummary(SettlementBaseSchema):
    """Summary of debtor or creditor amount."""

    user_id: uuid.UUID
    amount_paise: int


class GroupBalancesResponse(SettlementBaseSchema):
    """Complete balance breakdown for a group."""

    group_id: uuid.UUID
    net_positions: dict[str, int]
    suggested_transfers: list[dict[str, Any]]
    members: list[MemberBalanceItem]
    debtors: list[DebtorCreditorSummary]
    creditors: list[DebtorCreditorSummary]
    total_debt_paise: int
    currency: str = "INR"


class SimplifiedRepaymentsResponse(SettlementBaseSchema):
    """Simplified repayment suggestions minimizing transactions."""

    group_id: uuid.UUID
    suggested_transfers: list[dict[str, Any]]
    total_transfers: int
    total_amount_paise: int
