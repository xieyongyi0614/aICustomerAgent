from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LedgerDirection = Literal["expense", "income", "transfer"]
LedgerSource = Literal["conversation", "action", "manual", "import"]
LedgerAccountType = Literal["cash", "bank", "ewallet", "credit", "other"]
LedgerCategoryKind = Literal["expense", "income"]
LedgerAccountStatus = Literal["active", "archived"]


class LedgerAmountError(ValueError):
    pass


def to_minor(amount: Decimal | str | int) -> int:
    if isinstance(amount, float):
        raise LedgerAmountError("禁止 float 金额，请使用 Decimal 或 str")
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise LedgerAmountError(f"非法金额: {amount!r}") from exc
    if value <= 0:
        raise LedgerAmountError(f"金额必须为正: {amount!r}")
    minor = value * 100
    if minor != minor.to_integral_value():
        raise LedgerAmountError(f"金额精度超出分: {amount!r}")
    return int(minor)


def to_major(minor: int) -> Decimal:
    if minor <= 0:
        raise LedgerAmountError(f"amount_minor 必须为正: {minor!r}")
    return (Decimal(minor) / Decimal(100)).quantize(Decimal("0.01"))


class LedgerAccount(BaseModel):
    id: str
    user_id: str
    name: str
    type: LedgerAccountType
    currency: str
    status: LedgerAccountStatus
    created_at: datetime
    updated_at: datetime


class LedgerCategory(BaseModel):
    id: str
    user_id: str
    parent_id: str | None = None
    name: str
    kind: LedgerCategoryKind
    aliases: list[str] = Field(default_factory=list)
    is_seed: bool = False
    created_at: datetime
    updated_at: datetime


class LedgerEntry(BaseModel):
    id: str
    user_id: str
    account_id: str
    category_id: str | None = None
    amount_minor: int = Field(gt=0)
    currency: str
    direction: LedgerDirection
    occurred_at: datetime
    merchant: str | None = None
    note: str | None = None
    source: LedgerSource
    source_ref: str | None = None
    idempotency_key: str
    reversal_of: str | None = None
    created_at: datetime

    @field_validator("amount_minor")
    @classmethod
    def _amount_is_int_minor(cls, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise LedgerAmountError("amount_minor 必须为整数分")
        return value


class LedgerEntryDraft(BaseModel):
    user_id: str
    account_id: str
    category_id: str | None = None
    amount_minor: int = Field(gt=0)
    currency: str = "CNY"
    direction: LedgerDirection
    occurred_at: datetime
    merchant: str | None = None
    note: str | None = None
    source: LedgerSource
    source_ref: str | None = None
    idempotency_key: str
    reversal_of: str | None = None


class LedgerExtraction(BaseModel):
    is_ledger_intent: bool = False
    amount_value: str | None = None
    currency_hint: str | None = None
    direction: LedgerDirection | None = None
    category_hint: str | None = None
    merchant_hint: str | None = None
    occurred_at_hint: str | None = None
    occurred_at_resolved: datetime | None = None
    account_hint: str | None = None
    evidence_span: str | None = None
    confidence: float = 0.0
    missing_fields: tuple[str, ...] = ()
