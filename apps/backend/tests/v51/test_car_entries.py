"""API-019 养车入账编排用例（费用只落一次账 + 保养双写回链）。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.repositories import car_repository, ledger_repository
from app.services.car import entries as car_entries

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 30, 12, 0, 0)
USER = "car-entry-user"
KEY = "car-key-0001"


def _category_id(user_id: str, name: str) -> str:
    for row in ledger_repository.list_categories(user_id):
        if row.name == name:
            return row.id
    raise AssertionError(f"缺少分类: {name}")


def _entries(user_id: str, *, include_reversals: bool = True):
    return ledger_repository.list_entries(
        user_id, include_reversals=include_reversals
    )


def test_record_car_expense_charge_lands_in_car_charge_category(db_session_factory):
    outcome = car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key=KEY,
        now=NOW,
    )

    assert outcome.entry_id is not None
    assert outcome.record_id is None
    assert outcome.category_name == "充电"
    assert outcome.hint == car_entries.LINKAGE_HINT
    rows = _entries(USER)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row.amount_minor, int)
    assert row.amount_minor == 4200
    assert row.category_id == _category_id(USER, "充电")
    assert row.direction == "expense"
    assert row.source == "manual"
    assert row.source_ref == "car:charge"


def test_record_car_expense_fuel_parking_toll_map_to_car_subcategories(
    db_session_factory,
):
    for index, (kind, name) in enumerate(
        (("fuel", "加油费"), ("parking", "停车费"), ("toll", "过路"))
    ):
        outcome = car_entries.record_car_expense(
            USER,
            kind=kind,
            amount_minor=1000 * (index + 1),
            occurred_at=NOW,
            idempotency_key=f"car-key-{kind}-01",
            now=NOW,
        )
        assert outcome.category_name == name
        row = ledger_repository.get_entry(outcome.entry_id)
        assert row.category_id == _category_id(USER, name)


def test_record_car_expense_mileage_creates_no_ledger_entry(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key=KEY,
        now=NOW,
    )
    before = len(_entries(USER, include_reversals=False))

    outcome = car_entries.record_car_expense(
        USER,
        kind="mileage",
        odometer_km=12480,
        occurred_at=NOW,
        note="通勤往返",
        idempotency_key="car-key-mileage1",
        now=NOW,
    )

    assert outcome.entry_id is None
    assert outcome.category_name == ""
    assert outcome.hint == car_entries.MILEAGE_HINT
    assert len(_entries(USER, include_reversals=False)) == before
    logs = car_repository.list_mileage_logs(USER)
    assert len(logs) == 1
    assert logs[0].odometer_km == 12480
    assert logs[0].delta_km is None
    assert car_repository.get_profile(USER).odometer_km == 12480


def test_mileage_second_record_reports_delta(db_session_factory):
    car_entries.record_car_expense(
        USER,
        kind="mileage",
        odometer_km=12400,
        occurred_at=NOW,
        idempotency_key="car-key-mileage1",
        now=NOW,
    )
    outcome = car_entries.record_car_expense(
        USER,
        kind="mileage",
        odometer_km=12480,
        occurred_at=NOW,
        note="通勤往返",
        idempotency_key="car-key-mileage2",
        now=NOW,
    )

    assert outcome.odometer_delta_km == 80
    assert car_repository.get_profile(USER).odometer_km == 12480


def test_record_car_expense_service_writes_record_and_backlinks_entry(
    db_session_factory,
):
    outcome = car_entries.record_car_expense(
        USER,
        kind="service",
        amount_minor=20000,
        note="小保养 · 机油机滤",
        place="华迪 4S 店",
        odometer_km=10380,
        occurred_at=NOW,
        idempotency_key="car-key-service1",
        now=NOW,
    )

    assert outcome.entry_id is not None
    assert outcome.record_id is not None
    assert outcome.category_name == "保养"
    records = car_repository.list_service_records(USER)
    assert len(records) == 1
    record = records[0]
    assert record.ledger_entry_id == outcome.entry_id
    assert record.title == "小保养 · 机油机滤"
    assert record.place == "华迪 4S 店"
    assert record.amount_minor == 20000
    assert (
        record.amount_minor
        == ledger_repository.get_entry(outcome.entry_id).amount_minor
    )


def test_record_car_expense_service_rollback_on_second_step_failure(
    db_session_factory, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("档案库不可写")

    monkeypatch.setattr(car_repository, "create_service_record", boom)

    with pytest.raises(car_entries.CarEntryError):
        car_entries.record_car_expense(
            USER,
            kind="service",
            amount_minor=20000,
            note="小保养",
            occurred_at=NOW,
            idempotency_key="car-key-service2",
            now=NOW,
        )

    rows = _entries(USER, include_reversals=False)
    assert len(rows) == 1
    assert rows[0].reversal_of is None
    reversal = ledger_repository.reversal_of(rows[0].id)
    assert reversal is not None
    assert car_repository.list_service_records(USER) == []


def test_record_car_expense_is_idempotent_by_key(db_session_factory):
    first = car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key=KEY,
        now=NOW,
    )
    second = car_entries.record_car_expense(
        USER,
        kind="charge",
        amount_minor=4200,
        occurred_at=NOW,
        idempotency_key=KEY,
        now=NOW,
    )

    assert first.entry_id == second.entry_id
    assert len(_entries(USER, include_reversals=False)) == 1


def test_record_car_expense_rejects_invalid_inputs(db_session_factory):
    with pytest.raises(car_entries.CarEntryError):
        car_entries.record_car_expense(
            USER,
            kind="flight",
            amount_minor=100,
            occurred_at=NOW,
            idempotency_key=KEY,
            now=NOW,
        )
    with pytest.raises(car_entries.CarEntryError):
        car_entries.record_car_expense(
            USER,
            kind="charge",
            amount_minor=100,
            occurred_at=NOW,
            idempotency_key="short",
            now=NOW,
        )
    with pytest.raises(car_entries.CarEntryError):
        car_entries.record_car_expense(
            USER,
            kind="charge",
            amount_minor=0,
            occurred_at=NOW,
            idempotency_key=KEY,
            now=NOW,
        )
    with pytest.raises(car_entries.CarEntryError):
        car_entries.record_car_expense(
            USER,
            kind="mileage",
            occurred_at=NOW,
            idempotency_key=KEY,
            now=NOW,
        )

    assert _entries(USER) == []
    assert car_repository.get_profile(USER) is None
