"""PLA-010 订正 = 冲正 + 新增；撤销 = 冲正。append-only，永不 UPDATE 金额。

口径冻结（对冲正行再冲正）：**拒绝**——`reverse_entry` 已禁止冲正行二次冲正，
本模块不放宽该语义。恢复净额须走「撤销冲正的冲正」之外的显式新账（后续版本）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.ledger.service import (
    LedgerReversalError,
    LedgerValidationError,
    record_entry,
    reverse_entry,
)

_CHANGE_FIELDS = (
    "amount_minor",
    "currency",
    "direction",
    "occurred_at",
    "merchant",
    "note",
    "category_id",
    "account_id",
)


@dataclass(frozen=True, slots=True)
class CorrectionOutcome:
    original_entry_id: str
    reversal_entry_id: str
    new_entry_id: str | None
    net_effect_minor: int


def _signed(entry) -> int:
    amount = int(entry.amount_minor)
    if entry.direction == "expense":
        return -amount
    if entry.direction == "income":
        return amount
    return 0


def revise_entry(
    entry_id: str,
    changes: Mapping[str, Any],
    *,
    reason: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> CorrectionOutcome:
    """修改 = 冲正原条目 + 按 changes 新增；原行逐字节未变。"""
    original = ledger_repository.get_entry(entry_id)
    if original is None:
        raise LedgerReversalError("条目不存在")
    existing_reversal = ledger_repository.reversal_of(entry_id)
    if existing_reversal is not None:
        if existing_reversal.idempotency_key.startswith(idempotency_key):
            new_row = next(
                (
                    row
                    for row in ledger_repository.list_entries(original.user_id)
                    if row.idempotency_key == f"{idempotency_key}:new"
                ),
                None,
            )
            return CorrectionOutcome(
                original_entry_id=entry_id,
                reversal_entry_id=existing_reversal.id,
                new_entry_id=new_row.id if new_row else None,
                net_effect_minor=_signed(existing_reversal)
                + (_signed(new_row) if new_row else 0),
            )
        raise LedgerReversalError("条目已冲正")

    reversal = reverse_entry(
        entry_id,
        reason=reason,
        idempotency_key=f"{idempotency_key}:rev",
        now=now,
    )
    draft_values: dict[str, Any] = {
        "user_id": original.user_id,
        "account_id": original.account_id,
        "category_id": original.category_id,
        "amount_minor": int(original.amount_minor),
        "currency": original.currency,
        "direction": original.direction,
        "occurred_at": original.occurred_at,
        "merchant": original.merchant,
        "note": reason,
        "source": original.source,
        "source_ref": original.source_ref,
        "idempotency_key": f"{idempotency_key}:new",
    }
    for field in _CHANGE_FIELDS:
        if field in changes and changes[field] is not None:
            draft_values[field] = changes[field]
    if isinstance(draft_values.get("occurred_at"), str):
        from datetime import datetime as _dt

        draft_values["occurred_at"] = _dt.fromisoformat(str(draft_values["occurred_at"]))
    draft = LedgerEntryDraft(**draft_values)
    created = record_entry(draft, idempotency_key=draft.idempotency_key, now=now)
    return CorrectionOutcome(
        original_entry_id=entry_id,
        reversal_entry_id=reversal.entry.id,
        new_entry_id=created.entry.id,
        net_effect_minor=_signed(reversal.entry) + _signed(created.entry),
    )


def cancel_entry(
    entry_id: str,
    *,
    reason: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> CorrectionOutcome:
    """撤销 = 冲正原条目；净额归零，原行保留。"""
    original = ledger_repository.get_entry(entry_id)
    if original is None:
        raise LedgerReversalError("条目不存在")
    reversal = reverse_entry(
        entry_id,
        reason=reason,
        idempotency_key=idempotency_key,
        now=now,
    )
    return CorrectionOutcome(
        original_entry_id=entry_id,
        reversal_entry_id=reversal.entry.id,
        new_entry_id=None,
        net_effect_minor=_signed(reversal.entry) + _signed(original),
    )


__all__ = [
    "CorrectionOutcome",
    "cancel_entry",
    "revise_entry",
]
