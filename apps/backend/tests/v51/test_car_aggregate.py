"""API-019 养车支出聚合与最近记录用例。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.ledger import LedgerEntryDraft
from app.repositories import car_repository, ledger_repository
from app.services.car import aggregate as car_aggregate
from app.services.car import entries as car_entries
from app.services.ledger import query as ledger_query
from app.services.ledger import service as ledger_service

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 30, 12, 0, 0)
PREVIOUS_MONTH = datetime(2026, 8, 15, 12, 0, 0)
USER = "car-aggregate-user"


def _category_id(user_id: str, name: str) -> str:
    for row in ledger_repository.list_categories(user_id):
        if row.name == name:
            return row.id
    raise AssertionError(f"缺少分类: {name}")


def _raw_entry(
    user_id: str,
    *,
    category_name: str,
    amount_minor: int,
    occurred_at: datetime,
    key: str,
    direction: str = "expense",
):
    account_id = ledger_service.resolve_account_id(user_id)
    draft = LedgerEntryDraft(
        user_id=user_id,
        account_id=account_id,
        category_id=_category_id(user_id, category_name),
        amount_minor=amount_minor,
        direction=direction,
        occurred_at=occurred_at,
        note="手工入账",
        source="manual",
        idempotency_key=key,
    )
    return ledger_service.record_entry(draft, idempotency_key=key, now=occurred_at)


def _breakdown_by_name(user_id: str) -> dict[str, car_aggregate.CarExpenseLine]:
    return {
        line.category_name: line
        for line in car_aggregate.car_expense_breakdown(user_id, now=NOW)
    }


def test_aggregate_includes_transport_fuel_and_parking(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key="agg-key-charge",
        now=NOW,
    )
    _raw_entry(
        USER,
        category_name="加油",
        amount_minor=10000,
        occurred_at=NOW,
        key="agg-key-transport-fuel",
    )
    _raw_entry(
        USER,
        category_name="停车",
        amount_minor=5000,
        occurred_at=NOW,
        key="agg-key-transport-parking",
    )

    lines = _breakdown_by_name(USER)

    assert lines["充电"].net_minor == 4200
    assert lines["加油费"].net_minor == 10000
    assert lines["停车费"].net_minor == 5000
    assert lines["加油费"].category_id == _category_id(USER, "加油费")
    assert lines["停车费"].category_id == _category_id(USER, "停车费")


def test_aggregate_excludes_zero_value_subcategories(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key="agg-key-charge",
        now=NOW,
    )

    lines = car_aggregate.car_expense_breakdown(USER, now=NOW)

    assert [line.category_name for line in lines] == ["充电"]


def test_aggregate_ordering_is_desc_by_net_minor(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key="agg-key-charge",
        now=NOW,
    )
    car_entries.record_car_expense(
        USER,
        kind="toll",
        amount_minor=13000,
        occurred_at=NOW,
        idempotency_key="agg-key-toll",
        now=NOW,
    )
    car_entries.record_car_expense(
        USER,
        kind="fuel",
        amount_minor=10000,
        occurred_at=NOW,
        idempotency_key="agg-key-fuel",
        now=NOW,
    )

    lines = car_aggregate.car_expense_breakdown(USER, now=NOW)

    assert [line.category_name for line in lines] == ["过路", "加油费", "充电"]
    assert [line.net_minor for line in lines] == [13000, 10000, 4200]


def test_aggregate_is_month_scoped(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key="agg-key-charge",
        now=NOW,
    )
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=9999,
        occurred_at=PREVIOUS_MONTH,
        idempotency_key="agg-key-charge-prev",
        now=PREVIOUS_MONTH,
    )

    lines = car_aggregate.car_expense_breakdown(USER, now=NOW)

    assert sum(line.net_minor for line in lines) == 4200


def test_aggregate_amounts_match_ledger_summary(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key="agg-key-charge",
        now=NOW,
    )
    _raw_entry(
        USER,
        category_name="加油",
        amount_minor=10000,
        occurred_at=NOW,
        key="agg-key-transport-fuel",
    )

    lines = car_aggregate.car_expense_breakdown(USER, now=NOW)
    summary = ledger_query.summary(
        USER,
        period=ledger_query.Period.month(NOW),
        now=NOW,
        compare_previous=False,
    )
    folded_ids = [
        item.category_id for item in car_aggregate.car_category_targets(USER)
    ]
    summary_fold = -sum(summary.by_category.get(cid, 0) for cid in folded_ids)

    assert car_aggregate.car_expense_total(lines) == summary_fold == 14200


def test_aggregate_ignores_income_and_reversed_entries(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key="agg-key-charge",
        now=NOW,
    )
    charged = ledger_repository.list_entries(USER, include_reversals=False)[0]
    from app.services.ledger import correction as ledger_correction

    ledger_correction.cancel_entry(
        charged.id,
        reason="订正",
        idempotency_key="agg-key-revert",
        now=NOW,
    )

    lines = car_aggregate.car_expense_breakdown(USER, now=NOW)

    assert lines == []


def test_recent_records_merges_ledger_and_mileage_rows(db_session_factory):
    charge_at = datetime(2026, 9, 20, 9, 0, 0)
    first_mileage_at = datetime(2026, 9, 21, 9, 0, 0)
    second_mileage_at = datetime(2026, 9, 25, 9, 0, 0)
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=charge_at,
        note="快充",
        idempotency_key="agg-key-charge",
        now=NOW,
    )
    car_entries.record_car_expense(
        USER,
        kind="mileage",
        odometer_km=12400,
        occurred_at=first_mileage_at,
        idempotency_key="agg-key-mileage1",
        now=NOW,
    )
    car_entries.record_car_expense(
        USER,
        kind="mileage",
        odometer_km=12480,
        occurred_at=second_mileage_at,
        note="通勤往返",
        idempotency_key="agg-key-mileage2",
        now=NOW,
    )

    records = car_aggregate.car_recent_records(USER, limit=10)

    assert [record.kind for record in records] == ["mileage", "mileage", "charge"]
    assert records[0].occurred_at == second_mileage_at
    assert records[0].net_minor is None
    assert records[0].odometer_delta_km == 80
    assert records[1].odometer_delta_km is None
    charge = records[-1]
    assert charge.kind == "charge"
    assert charge.title == "快充"
    assert charge.subtitle is None
    assert charge.net_minor == 4200
    assert charge.ledger_entry_id is not None


def test_recent_records_respects_limit(db_session_factory):
    for index in range(3):
        car_entries.record_car_expense(
            USER,
            kind="charge",
            amount_minor=1000 + index,
            occurred_at=datetime(2026, 9, 20 + index, 9, 0, 0),
            idempotency_key=f"agg-key-limit-{index}",
            now=NOW,
        )

    records = car_aggregate.car_recent_records(USER, limit=2)

    assert len(records) == 2
    assert records[0].occurred_at == datetime(2026, 9, 22, 9, 0, 0)


def test_recent_records_exclude_other_categories(db_session_factory):
    _raw_entry(
        USER,
        category_name="数码",
        amount_minor=320000,
        occurred_at=NOW,
        key="agg-key-digital",
    )

    assert car_aggregate.car_recent_records(USER, limit=10) == []
    assert car_repository.list_mileage_logs(USER) == []
