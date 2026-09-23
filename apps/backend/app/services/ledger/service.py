from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.character.asuna.ledger_categories import SEED_CATEGORY_TREE
from app.core.db import LedgerEntryRow
from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.governance.models import DomainHandlers, ProvenanceRef
from app.services.governance.provenance import record_provenance
from app.services.governance.registry import register_domain

_REVERSE_DIRECTION = {"expense": "income", "income": "expense", "transfer": "transfer"}


class LedgerValidationError(ValueError):
    pass


class LedgerReversalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    entry: LedgerEntryRow
    created: bool
    reason: str


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    user_id: str
    account_created: bool
    categories_created: int
    created_at: datetime


def record_entry(
    draft: LedgerEntryDraft, *, idempotency_key: str, now: datetime | None = None
) -> RecordOutcome:
    if draft.amount_minor <= 0:
        raise LedgerValidationError("amount_minor 必须为正")
    if draft.direction not in ("expense", "income", "transfer"):
        raise LedgerValidationError("非法 direction")
    account = ledger_repository.get_account(draft.account_id)
    if account is None:
        raise LedgerValidationError("账户不存在")
    if account.user_id != draft.user_id:
        raise LedgerValidationError("账户不属于该用户")
    if draft.category_id:
        category = ledger_repository.get_category(draft.category_id)
        if category is None:
            raise LedgerValidationError("类目不存在")
        if category.user_id != draft.user_id:
            raise LedgerValidationError("类目不属于该用户")
    entry, created = ledger_repository.create_entry(
        draft, idempotency_key=idempotency_key, now=now
    )
    if created:
        record_provenance(
            ProvenanceRef(
                domain="ledger",
                record_id=entry.id,
                source=draft.source,
                source_ref=draft.source_ref or "",
            ),
            now=now,
        )
    return RecordOutcome(
        entry=entry,
        created=created,
        reason="created" if created else "idempotent_hit",
    )


def reverse_entry(
    entry_id: str,
    *,
    reason: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> RecordOutcome:
    original = ledger_repository.get_entry(entry_id)
    if original is None:
        raise LedgerReversalError("条目不存在")
    if original.reversal_of is not None:
        raise LedgerReversalError("冲正行不可再冲正")
    existing = ledger_repository.reversal_of(entry_id)
    if existing is not None:
        return RecordOutcome(
            entry=existing, created=False, reason="idempotent_hit"
        )
    outcome = ledger_repository.create_entry(
        LedgerEntryDraft(
            user_id=original.user_id,
            account_id=original.account_id,
            category_id=original.category_id,
            amount_minor=original.amount_minor,
            currency=original.currency,
            direction=_REVERSE_DIRECTION[original.direction],
            occurred_at=now or original.occurred_at,
            merchant=original.merchant,
            note=reason,
            source=original.source,
            source_ref=original.source_ref,
            idempotency_key=idempotency_key,
            reversal_of=original.id,
        ),
        idempotency_key=idempotency_key,
        now=now,
    )
    entry, created = outcome
    return RecordOutcome(
        entry=entry,
        created=created,
        reason="reversed" if created else "idempotent_hit",
    )


def resolve_account_id(user_id: str, account_id: str | None = None) -> str:
    ensure_user_bootstrap(user_id)
    if account_id:
        return account_id
    account, _created = ledger_repository.ensure_default_account(user_id)
    return account.id


def ensure_user_bootstrap(
    user_id: str, *, now: datetime | None = None
) -> BootstrapReport:
    timestamp = now or datetime.now()
    _account, account_created = ledger_repository.ensure_default_account(
        user_id, now=timestamp
    )
    categories_created = ledger_repository.ensure_seed_categories(
        user_id, seed_tree=SEED_CATEGORY_TREE, now=timestamp
    )
    return BootstrapReport(
        user_id=user_id,
        account_created=account_created,
        categories_created=categories_created,
        created_at=timestamp,
    )


def export_ledger_data(user_id: str):
    accounts = ledger_repository.list_accounts(user_id, include_archived=True)
    categories = ledger_repository.list_categories(user_id)
    entries = ledger_repository.list_entries(user_id)
    return {
        "accounts": [
            {
                "id": row.id,
                "name": row.name,
                "type": row.type,
                "currency": row.currency,
                "status": row.status,
            }
            for row in accounts
        ],
        "categories": [
            {
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                "parent_id": row.parent_id,
                "aliases": list(row.aliases or []),
            }
            for row in categories
        ],
        "entries": [
            {
                "id": row.id,
                "account_id": row.account_id,
                "category_id": row.category_id,
                "amount_minor": row.amount_minor,
                "currency": row.currency,
                "direction": row.direction,
                "occurred_at": row.occurred_at.isoformat(),
                "source": row.source,
                "source_ref": row.source_ref,
                "idempotency_key": row.idempotency_key,
                "reversal_of": row.reversal_of,
            }
            for row in entries
        ],
    }


def delete_ledger_data(user_id: str) -> int:
    deleted = 0
    deleted += ledger_repository.delete_entries_for_user(user_id)
    deleted += ledger_repository.delete_categories_for_user(user_id)
    deleted += ledger_repository.delete_accounts_for_user(user_id)
    return deleted


def resolve_ledger_provenance(record_id: str) -> ProvenanceRef | None:
    entry = ledger_repository.get_entry(record_id)
    if entry is None:
        return None
    return ProvenanceRef(
        domain="ledger",
        record_id=entry.id,
        source=entry.source,
        source_ref=entry.source_ref or "",
    )


def _register_governance() -> None:
    register_domain(
        DomainHandlers(
            name="ledger",
            export=export_ledger_data,
            delete=delete_ledger_data,
            provenance=lambda domain, rid: resolve_ledger_provenance(rid),
        )
    )


_register_governance()
