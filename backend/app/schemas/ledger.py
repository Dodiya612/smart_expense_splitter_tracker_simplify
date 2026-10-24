"""Schemas for the pure ledger engine, splits, settlements, and repayments."""

from enum import Enum
from typing import Any, Dict, Iterator, Optional, Union

from pydantic import BaseModel, Field, model_validator


class SplitMode(str, Enum):
    """Supported split modes for shared expenses."""

    EQUAL = "equal"
    EXACT = "exact"
    PERCENTAGE = "percentage"
    PARTS = "parts"


class ExpenseRecord(BaseModel):
    """Record of an expense representing cash paid and allocated shares."""

    expense_id: Optional[str] = Field(
        default=None, description="Unique identifier of the expense."
    )
    description: Optional[str] = Field(
        default=None, description="Brief description of the expense."
    )
    amount_paise: Optional[int] = Field(
        default=None, description="Total expense amount in whole paise."
    )
    paid_by: Optional[Union[str, Dict[str, int]]] = Field(
        default=None,
        description="Single payer ID or mapping of payer IDs to paise paid.",
    )
    payer_id: Optional[str] = Field(default=None, description="Single payer ID alias.")
    paid_by_user_id: Optional[str] = Field(
        default=None,
        description="Single payer ID alias matching API contracts.",
    )
    payments: Optional[Dict[str, int]] = Field(
        default=None,
        description="Payer IDs mapped to paise paid (mixed contributions).",
    )
    shares: Dict[str, int] = Field(
        ...,
        description="Mapping of participant IDs to their allocated share in paise.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "paid_by_user_id" in data and "payer_id" not in data:
                data["payer_id"] = data["paid_by_user_id"]
            if (
                "paid_by" in data
                and isinstance(data["paid_by"], str)
                and "payer_id" not in data
            ):
                data["payer_id"] = data["paid_by"]
        return data

    def get_payments(self) -> Dict[str, int]:
        """Return a mapping of payer ID to cash paid in paise."""
        if self.payments:
            return {k: v for k, v in self.payments.items() if v > 0}
        if isinstance(self.paid_by, dict):
            return {k: v for k, v in self.paid_by.items() if v > 0}
        payer = (
            self.payer_id
            or self.paid_by_user_id
            or (self.paid_by if isinstance(self.paid_by, str) else None)
        )
        if payer:
            total = (
                self.amount_paise
                if self.amount_paise is not None
                else sum(self.shares.values())
            )
            return {payer: total}
        return {}


class SettlementRecord(BaseModel):
    """Record of a debt settlement / repayment between two members."""

    settlement_id: Optional[str] = Field(
        default=None, description="Unique identifier of the settlement."
    )
    from_user: str = Field(..., description="User ID of member paying / debtor.")
    to_user: str = Field(
        ..., description="User ID of member receiving payment / creditor."
    )
    amount_paise: int = Field(
        ..., gt=0, description="Repayment amount in positive integer paise."
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "from_user" not in data:
                if "payer_id" in data:
                    data["from_user"] = data["payer_id"]
                elif "debtor_id" in data:
                    data["from_user"] = data["debtor_id"]
                elif "from_user_id" in data:
                    data["from_user"] = data["from_user_id"]
            if "to_user" not in data:
                if "payee_id" in data:
                    data["to_user"] = data["payee_id"]
                elif "creditor_id" in data:
                    data["to_user"] = data["creditor_id"]
                elif "to_user_id" in data:
                    data["to_user"] = data["to_user_id"]
        return data

    @property
    def payer_id(self) -> str:
        return self.from_user

    @property
    def payee_id(self) -> str:
        return self.to_user

    @property
    def debtor_id(self) -> str:
        return self.from_user

    @property
    def creditor_id(self) -> str:
        return self.to_user


class SuggestedTransfer(BaseModel):
    """Suggested repayment transfer resulting from debt simplification."""

    from_user: str = Field(..., description="User ID of debtor who repays.")
    to_user: str = Field(..., description="User ID of creditor who receives payment.")
    amount_paise: int = Field(
        ..., gt=0, description="Settlement amount in integer paise."
    )

    @property
    def payer_id(self) -> str:
        return self.from_user

    @property
    def payee_id(self) -> str:
        return self.to_user

    @property
    def debtor_id(self) -> str:
        return self.from_user

    @property
    def creditor_id(self) -> str:
        return self.to_user

    def __iter__(self) -> Iterator[Union[str, int]]:
        """Support tuple unpacking: debtor, creditor, amount = transfer."""
        return iter((self.from_user, self.to_user, self.amount_paise))
