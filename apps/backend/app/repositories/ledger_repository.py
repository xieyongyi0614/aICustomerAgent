from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core import ids
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
            id=ids.new_id_str(),
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
            id=ids.new_id_str(),
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
            id=ids.new_id_str(),
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


def append_category_alias(user_id: str, category_id: str, alias: str) -> bool:
    with SessionLocal() as session:
        row = session.get(LedgerCategoryRow, category_id)
        if row is None or row.user_id != user_id:
            return False
        aliases = list(row.aliases or [])
        if alias not in aliases:
            aliases.append(alias)
            row.aliases = aliases
            session.commit()
        return True


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
    """播种分类树。

    种子 id 保持确定性（`cat_seed_{user_id}_{原始名}`）而非雪花：它承担**跨重命名的稳定身份**
    ——用户把「餐饮」改成「吃饭」后重跑播种，不能把原分类复活。这是 ADR-16 §6.2 登记的
    例外表之一，待引入 `seed_key` 列（雪花 id + 业务唯一键）后再收敛。
    """
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


def _period_filter(query, since: datetime | None, until: datetime | None):
    if since is not None:
        query = query.filter(LedgerEntryRow.occurred_at >= since)
    if until is not None:
        query = query.filter(LedgerEntryRow.occurred_at < until)
    return query


def sum_by_direction(
    user_id: str, since: datetime | None = None, until: datetime | None = None
) -> dict[str, int]:
    from sqlalchemy import func

    with SessionLocal() as session:
        query = _period_filter(
            session.query(
                LedgerEntryRow.direction,
                func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0),
            ).filter(LedgerEntryRow.user_id == user_id),
            since,
            until,
        ).group_by(LedgerEntryRow.direction)
        return {direction: int(total) for direction, total in query.all()}


def sum_by_category(
    user_id: str, since: datetime | None = None, until: datetime | None = None
) -> list[tuple[str | None, str, int]]:
    from sqlalchemy import func

    with SessionLocal() as session:
        query = _period_filter(
            session.query(
                LedgerEntryRow.category_id,
                LedgerEntryRow.direction,
                func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0),
            ).filter(LedgerEntryRow.user_id == user_id),
            since,
            until,
        ).group_by(LedgerEntryRow.category_id, LedgerEntryRow.direction)
        return [
            (category_id, direction, int(total))
            for category_id, direction, total in query.all()
        ]


def sum_by_account(
    user_id: str, since: datetime | None = None, until: datetime | None = None
) -> list[tuple[str, str, int]]:
    from sqlalchemy import func

    with SessionLocal() as session:
        query = _period_filter(
            session.query(
                LedgerEntryRow.account_id,
                LedgerEntryRow.direction,
                func.coalesce(func.sum(LedgerEntryRow.amount_minor), 0),
            ).filter(LedgerEntryRow.user_id == user_id),
            since,
            until,
        ).group_by(LedgerEntryRow.account_id, LedgerEntryRow.direction)
        return [
            (account_id, direction, int(total))
            for account_id, direction, total in query.all()
        ]


def count_period_entries(
    user_id: str, since: datetime | None = None, until: datetime | None = None
) -> tuple[int, int, int]:
    """返回 (全部行数, 冲正行数, 被冲正的原条目数)。"""
    with SessionLocal() as session:
        base = session.query(LedgerEntryRow).filter(
            LedgerEntryRow.user_id == user_id
        )
        base = _period_filter(base, since, until)
        total = base.count()
        reversals = base.filter(LedgerEntryRow.reversal_of.isnot(None)).count()
        reversed_ids = {
            row.reversal_of
            for row in base.filter(LedgerEntryRow.reversal_of.isnot(None)).all()
            if row.reversal_of
        }
        return int(total), int(reversals), len(reversed_ids)


def sum_signed_minor(
    user_id: str, since: datetime | None = None, until: datetime | None = None
) -> tuple[int, int, int]:
    """返回 (expense净分, income净分, transfer分)。冲正双向计入。"""
    rows = list_entries(user_id, since=since, until=until)
    expense = 0
    income = 0
    transfer = 0
    for row in rows:
        amount = int(row.amount_minor)
        if row.reversal_of is not None:
            if row.direction == "income":
                expense -= amount
            elif row.direction == "expense":
                income -= amount
            elif row.direction == "transfer":
                transfer -= amount
            continue
        if row.direction == "expense":
            expense += amount
        elif row.direction == "income":
            income += amount
        elif row.direction == "transfer":
            transfer += amount
    return expense, income, transfer


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
