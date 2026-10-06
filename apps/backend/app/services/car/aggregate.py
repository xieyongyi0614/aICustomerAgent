from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core import timeutil
from app.repositories import car_repository, ledger_repository
from app.services.ledger import query as ledger_query

CAR_PARENT_NAME = "养车"
CAR_MILEAGE_KIND = "mileage"

KIND_CATEGORY_NAMES: dict[str, str] = {
    "charge": "充电",
    "fuel": "加油费",
    "parking": "停车费",
    "toll": "过路",
    "service": "保养",
}
CATEGORY_NAME_TO_KIND: dict[str, str] = {
    name: kind for kind, name in KIND_CATEGORY_NAMES.items()
}
LEGACY_TRANSPORT_TARGETS: dict[str, str] = {"加油": "加油费", "停车": "停车费"}


@dataclass(frozen=True, slots=True)
class CarCategoryTarget:
    category_id: str
    target_name: str
    primary: bool


@dataclass(frozen=True, slots=True)
class CarExpenseLine:
    category_id: str | None
    category_name: str
    net_minor: int
    count: int


@dataclass(frozen=True, slots=True)
class CarRecentRecord:
    kind: str
    title: str
    subtitle: str | None
    net_minor: int | None
    odometer_delta_km: int | None
    occurred_at: datetime
    source: str
    ledger_entry_id: str | None = None


def car_category_targets(user_id: str) -> list[CarCategoryTarget]:
    rows = ledger_repository.list_categories(user_id)
    parent = next(
        (
            row
            for row in rows
            if row.name == CAR_PARENT_NAME and row.parent_id is None
        ),
        None,
    )
    targets: list[CarCategoryTarget] = []
    for row in rows:
        if parent is not None and row.parent_id == parent.id:
            targets.append(CarCategoryTarget(row.id, row.name, True))
            continue
        legacy = LEGACY_TRANSPORT_TARGETS.get(row.name)
        if legacy is not None and row.parent_id is not None:
            targets.append(CarCategoryTarget(row.id, legacy, False))
    return targets


def _period_or_month(
    period: ledger_query.Period | None, now: datetime | None
) -> ledger_query.Period:
    return period or ledger_query.Period.month(timeutil.ensure_aware(now) or timeutil.now())


def car_expense_breakdown(
    user_id: str,
    *,
    period: ledger_query.Period | None = None,
    now: datetime | None = None,
) -> list[CarExpenseLine]:
    targets = car_category_targets(user_id)
    if not targets:
        return []
    name_by_category = {item.category_id: item.target_name for item in targets}
    primary_id: dict[str, str] = {}
    for item in targets:
        if item.primary and item.target_name not in primary_id:
            primary_id[item.target_name] = item.category_id
    window = _period_or_month(period, now)
    rows = ledger_repository.list_entries(user_id, since=window.since, until=window.until)
    net: dict[str, int] = {}
    counts: dict[str, int] = {}
    for row in rows:
        target_name = name_by_category.get(row.category_id or "")
        if target_name is None:
            continue
        amount = int(row.amount_minor)
        if row.direction == "expense":
            net[target_name] = net.get(target_name, 0) + amount
            if row.reversal_of is None:
                counts[target_name] = counts.get(target_name, 0) + 1
        elif row.direction == "income":
            net[target_name] = net.get(target_name, 0) - amount
    lines = [
        CarExpenseLine(
            category_id=primary_id.get(name),
            category_name=name,
            net_minor=value,
            count=counts.get(name, 0),
        )
        for name, value in net.items()
        if value > 0
    ]
    lines.sort(key=lambda line: (-line.net_minor, line.category_name))
    return lines


def car_expense_total(lines: list[CarExpenseLine]) -> int:
    return sum(line.net_minor for line in lines)


def car_recent_records(
    user_id: str, *, limit: int = 10, now: datetime | None = None
) -> list[CarRecentRecord]:
    targets = car_category_targets(user_id)
    name_by_category = {item.category_id: item.target_name for item in targets}
    records: list[CarRecentRecord] = []
    for row in ledger_repository.list_entries(user_id, include_reversals=False):
        target_name = name_by_category.get(row.category_id or "")
        if target_name is None or row.direction != "expense":
            continue
        records.append(
            CarRecentRecord(
                kind=CATEGORY_NAME_TO_KIND.get(target_name, "expense"),
                title=row.note or target_name,
                subtitle=row.merchant,
                net_minor=int(row.amount_minor),
                odometer_delta_km=None,
                occurred_at=row.occurred_at,
                source=row.source,
                ledger_entry_id=row.id,
            )
        )
    for log in car_repository.list_mileage_logs(user_id):
        records.append(
            CarRecentRecord(
                kind=CAR_MILEAGE_KIND,
                title="里程",
                subtitle=log.note,
                net_minor=None,
                odometer_delta_km=log.delta_km,
                occurred_at=log.recorded_at,
                source="car",
            )
        )
    records.sort(key=lambda record: record.occurred_at, reverse=True)
    return records[: max(0, limit)]
