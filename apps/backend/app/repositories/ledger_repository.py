from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.db import (
    LedgerAccountRow,
    LedgerCategoryRow,
    LedgerEntryRow,
    SessionLocal,
)
from app.models.ledger import LedgerEntryDraft


def create_account(
    user_id: str,
    name: str,
    type: str,
    *,
    currency: str = "CNY",
    now: datetime | None = None,
) -> LedgerAccountRow:
    timestamp = now or datetime.now()
    with SessionLocal() as session:
        row = LedgerAccountRow(
            id=f"acc_{user_id}_{name}_{int(timestamp.timestamp() * 1000)}",
            user_id=user_id,
            name=name,
            type=type,
            currency=currency,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def get_account(account_id: str) -> LedgerAccountRow | None:
    with SessionLocal() as session:
        return session.get(LedgerAccountRow, account_id)


def list_accounts(user_id: str, *, include_archived: bool = False):
    with SessionLocal() as session:
        query = session.query(LedgerAccountRow).filter(
            LedgerAccountRow.user_id == user_id
        )
        if not include_archived:
            query = query.filter(LedgerAccountRow.status == "active")
        rows = query.order_by(LedgerAccountRow.created_at).all()
        for row in rows:
            session.expunge(row)
        return rows


def ensure_default_account(
    user_id: str, *, now: datetime | None = None
) -> tuple[LedgerAccountRow, bool]:
    timestamp = now or datetime.now()
    with SessionLocal() as session:
        existing = (
            session.query(LedgerAccountRow)
            .filter(
                LedgerAccountRow.user_id == user_id,
                LedgerAccountRow.name == "现金",
            )
            .first()
        )
        if existing is not None:
            session.expunge(existing)
            return existing, False
        row = LedgerAccountRow(
            id=f"acc_{user_id}_cash_default",
            user_id=user_id,
            name="现金",
            type="cash",
            currency="CNY",
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = (
                session.query(LedgerAccountRow)
                .filter(
                    LedgerAccountRow.user_id == user_id,
                    LedgerAccountRow.name == "现金",
                )
                .first()
            )
            session.expunge(existing)
            return existing, False
        session.refresh(row)
        session.expunge(row)
        return row, True


def create_category(
    user_id: str,
    name: str,
    kind: str,
    *,
    parent_id: str | None = None,
    aliases: list[str] | None = None,
    is_seed: bool = False,
    now: datetime | None = None,
) -> LedgerCategoryRow:
    timestamp = now or datetime.now()
    with SessionLocal() as session:
        row = LedgerCategoryRow(
            id=f"cat_{user_id}_{name}_{int(timestamp.timestamp() * 1000)}",
            user_id=user_id,
            parent_id=parent_id,
            name=name,
            kind=kind,
            aliases=aliases or [],
            is_seed=is_seed,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def get_category(category_id: str) -> LedgerCategoryRow | None:
    with SessionLocal() as session:
        return session.get(LedgerCategoryRow, category_id)


def list_categories(user_id: str, *, kind: str | None = None):
    with SessionLocal() as session:
        query = session.query(LedgerCategoryRow).filter(
            LedgerCategoryRow.user_id == user_id
        )
        if kind is not None:
            query = query.filter(LedgerCategoryRow.kind == kind)
        rows = query.order_by(LedgerCategoryRow.created_at).all()
        for row in rows:
            session.expunge(row)
        return rows


def find_by_alias(user_id: str, text: str) -> LedgerCategoryRow | None:
    if not text:
        return None
    with SessionLocal() as session:
        rows = (
            session.query(LedgerCategoryRow)
            .filter(LedgerCategoryRow.user_id == user_id)
            .all()
        )
        for row in rows:
            if row.name == text or text in (row.aliases or []):
                session.expunge(row)
                return row
        return None


def ensure_seed_categories(user_id: str, *, seed_tree, now: datetime | None = None) -> int:
    timestamp = now or datetime.now()
    created = 0
    by_name = {row.name: row for row in list_categories(user_id)}
    for node in seed_tree:
        seed_id = f"cat_seed_{user_id}_{node['name']}"
        if get_category(seed_id) is not None:
            continue
        parent = by_name.get(node["parent_name"])
        parent_id = parent.id if parent else None
        with SessionLocal() as session:
            session.add(
                LedgerCategoryRow(
                    id=seed_id,
                    user_id=user_id,
                    parent_id=parent_id,
                    name=node["name"],
                    kind=node["kind"],
                    aliases=node.get("aliases") or [],
                    is_seed=True,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                continue
        by_name[node["name"]] = get_category(seed_id)
        created += 1
    return created


def create_entry(
    draft: LedgerEntryDraft, *, idempotency_key: str, now: datetime | None = None
) -> tuple[LedgerEntryRow, bool]:
    timestamp = now or datetime.now()
    with SessionLocal() as session:
        existing = (
            session.query(LedgerEntryRow)
            .filter(LedgerEntryRow.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            session.expunge(existing)
            return existing, False
        row = LedgerEntryRow(
            id=f"ent_{idempotency_key}",
            user_id=draft.user_id,
            account_id=draft.account_id,
            category_id=draft.category_id,
            amount_minor=draft.amount_minor,
            currency=draft.currency,
            direction=draft.direction,
            occurred_at=draft.occurred_at,
            merchant=draft.merchant,
            note=draft.note,
            source=draft.source,
            source_ref=draft.source_ref,
            idempotency_key=idempotency_key,
            reversal_of=draft.reversal_of,
            created_at=timestamp,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = (
                session.query(LedgerEntryRow)
                .filter(LedgerEntryRow.idempotency_key == idempotency_key)
                .first()
            )
            session.expunge(existing)
            return existing, False
        session.refresh(row)
        session.expunge(row)
        return row, True


def get_entry(entry_id: str) -> LedgerEntryRow | None:
    with SessionLocal() as session:
        return session.get(LedgerEntryRow, entry_id)


def list_entries(
    user_id: str,
    *,
    account_id: str | None = None,
    category_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    direction: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    include_reversals: bool = True,
):
    with SessionLocal() as session:
        query = session.query(LedgerEntryRow).filter(
            LedgerEntryRow.user_id == user_id
        )
        if account_id is not None:
            query = query.filter(LedgerEntryRow.account_id == account_id)
        if category_id is not None:
            query = query.filter(LedgerEntryRow.category_id == category_id)
        if since is not None:
            query = query.filter(LedgerEntryRow.occurred_at >= since)
        if until is not None:
            query = query.filter(LedgerEntryRow.occurred_at < until)
        if direction is not None:
            query = query.filter(LedgerEntryRow.direction == direction)
        if not include_reversals:
            query = query.filter(LedgerEntryRow.reversal_of.is_(None))
        query = query.order_by(LedgerEntryRow.occurred_at, LedgerEntryRow.id)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows


def reversal_of(entry_id: str) -> LedgerEntryRow | None:
    with SessionLocal() as session:
        row = (
            session.query(LedgerEntryRow)
            .filter(LedgerEntryRow.reversal_of == entry_id)
            .first()
        )
        if row is not None:
            session.expunge(row)
        return row


def count_entries(user_id: str) -> int:
    with SessionLocal() as session:
        return (
            session.query(LedgerEntryRow)
            .filter(LedgerEntryRow.user_id == user_id)
            .count()
        )


def delete_entries_for_user(user_id: str) -> int:
    with SessionLocal() as session:
        count = (
            session.query(LedgerEntryRow)
            .filter(LedgerEntryRow.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.commit()
        return count


def delete_categories_for_user(user_id: str) -> int:
    with SessionLocal() as session:
        count = (
            session.query(LedgerCategoryRow)
            .filter(LedgerCategoryRow.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.commit()
        return count


def delete_accounts_for_user(user_id: str) -> int:
    with SessionLocal() as session:
        count = (
            session.query(LedgerAccountRow)
            .filter(LedgerAccountRow.user_id == user_id)
            .delete(synchronize_session=False)
        )
        session.commit()
        return count
