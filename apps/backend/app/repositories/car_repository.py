from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.core import timeutil
from app.core import ids
from app.core.db import (
    CarLoanRow,
    CarMileageLogRow,
    CarProfileRow,
    CarServiceRecordRow,
    SessionLocal,
)
from app.models.car import (
    CarLoanDraft,
    CarMileageLogDraft,
    CarServiceRecordDraft,
)

PROFILE_FIELDS = frozenset(
    {
        "model",
        "plate",
        "trim_note",
        "battery_kwh",
        "purchased_at",
        "odometer_km",
        "insurance_due_at",
        "insurance_note",
        "insurance_annual_minor",
        "inspection_due_at",
        "inspection_note",
        "charger_power_kw",
        "charger_note",
        "service_interval_km",
        "service_interval_months",
        "restriction_city",
        "restriction_digits",
        "restriction_weekday",
    }
)

LOAN_FIELDS = frozenset(
    {
        "principal_minor",
        "monthly_minor",
        "paid_periods",
        "total_periods",
        "next_due_at",
        "settled_at",
    }
)


def _new_id() -> str:
    return ids.new_id_str()


def get_profile(user_id: str) -> CarProfileRow | None:
    with SessionLocal() as session:
        row = (
            session.query(CarProfileRow)
            .filter(CarProfileRow.user_id == user_id)
            .first()
        )
        if row is not None:
            session.expunge(row)
        return row


def upsert_profile(
    user_id: str,
    values: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> CarProfileRow:
    unknown = set(values) - PROFILE_FIELDS
    if unknown:
        raise ValueError(f"未知档案字段: {sorted(unknown)}")
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = (
            session.query(CarProfileRow)
            .filter(CarProfileRow.user_id == user_id)
            .first()
        )
        if row is None:
            row = CarProfileRow(
                id=ids.new_id_str(),
                user_id=user_id,
                odometer_km=0,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = timestamp
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def get_loan(user_id: str) -> CarLoanRow | None:
    with SessionLocal() as session:
        row = (
            session.query(CarLoanRow).filter(CarLoanRow.user_id == user_id).first()
        )
        if row is not None:
            session.expunge(row)
        return row


def upsert_loan(
    user_id: str,
    values: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> CarLoanRow:
    unknown = set(values) - LOAN_FIELDS
    if unknown:
        raise ValueError(f"未知车贷字段: {sorted(unknown)}")
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = (
            session.query(CarLoanRow).filter(CarLoanRow.user_id == user_id).first()
        )
        if row is None:
            row = CarLoanRow(
                id=ids.new_id_str(),
                user_id=user_id,
                paid_periods=0,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(row)
        for key, value in values.items():
            setattr(row, key, value)
        row.updated_at = timestamp
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def create_service_record(
    user_id: str,
    draft: CarServiceRecordDraft,
    *,
    now: datetime | None = None,
) -> CarServiceRecordRow:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = CarServiceRecordRow(
            id=_new_id(),
            user_id=user_id,
            title=draft.title,
            place=draft.place,
            odometer_km=draft.odometer_km,
            occurred_at=draft.occurred_at,
            amount_minor=draft.amount_minor,
            next_due_at=draft.next_due_at,
            next_due_km=draft.next_due_km,
            ledger_entry_id=draft.ledger_entry_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def list_service_records(
    user_id: str, *, limit: int | None = None
) -> list[CarServiceRecordRow]:
    with SessionLocal() as session:
        query = (
            session.query(CarServiceRecordRow)
            .filter(CarServiceRecordRow.user_id == user_id)
            .order_by(
                CarServiceRecordRow.occurred_at.desc(),
                CarServiceRecordRow.id.desc(),
            )
        )
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows


def create_mileage_log(
    user_id: str,
    draft: CarMileageLogDraft,
    *,
    now: datetime | None = None,
) -> CarMileageLogRow:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = CarMileageLogRow(
            id=_new_id(),
            user_id=user_id,
            odometer_km=draft.odometer_km,
            delta_km=draft.delta_km,
            recorded_at=draft.recorded_at,
            note=draft.note,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def list_mileage_logs(
    user_id: str, *, limit: int | None = None
) -> list[CarMileageLogRow]:
    with SessionLocal() as session:
        query = (
            session.query(CarMileageLogRow)
            .filter(CarMileageLogRow.user_id == user_id)
            .order_by(
                CarMileageLogRow.recorded_at.desc(), CarMileageLogRow.id.desc()
            )
        )
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows


def latest_mileage_log(user_id: str) -> CarMileageLogRow | None:
    rows = list_mileage_logs(user_id, limit=1)
    return rows[0] if rows else None
