from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.car import (
    CAR_EXPENSE_KINDS,
    CAR_MILEAGE_KIND,
    CarMileageLogDraft,
    CarServiceRecordDraft,
)
from app.models.ledger import LedgerEntryDraft
from app.repositories import car_repository
from app.services.car.aggregate import KIND_CATEGORY_NAMES
from app.services.ledger import category as ledger_category
from app.services.ledger import correction as ledger_correction
from app.services.ledger import service as ledger_service

LINKAGE_HINT = "这笔费用会同时计入「生活 · 记账」的养车分类，不用重复记"
MILEAGE_HINT = "里程只记在这辆车上，不会产生账目"
MIN_IDEMPOTENCY_KEY_LENGTH = 8
CAR_SOURCE_REF_PREFIX = "car"


class CarEntryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CarExpenseOutcome:
    kind: str
    entry_id: str | None
    record_id: str | None
    category_id: str | None
    category_name: str
    normalized_from: str | None
    odometer_delta_km: int | None
    hint: str


def _apply_odometer(
    user_id: str,
    odometer_km: int | None,
    *,
    now: datetime | None,
) -> int | None:
    if odometer_km is None:
        return None
    if odometer_km < 0:
        raise CarEntryError("里程读数不能为负")
    profile = car_repository.get_profile(user_id)
    previous = int(profile.odometer_km) if profile is not None else 0
    delta = odometer_km - previous if previous > 0 and odometer_km >= previous else None
    car_repository.upsert_profile(
        user_id, {"odometer_km": max(previous, odometer_km)}, now=now
    )
    return delta


def _rollback_entry(
    entry_id: str, *, created: bool, idempotency_key: str, now: datetime | None
) -> None:
    if not created:
        return
    ledger_correction.cancel_entry(
        entry_id,
        reason="养车档案写入失败，账目已回滚",
        idempotency_key=f"{idempotency_key}:rollback",
        now=now,
    )


def record_car_expense(
    user_id: str,
    *,
    kind: str,
    idempotency_key: str,
    amount_minor: int | None = None,
    occurred_at: datetime | None = None,
    note: str | None = None,
    odometer_km: int | None = None,
    place: str | None = None,
    source: str = "manual",
    now: datetime | None = None,
) -> CarExpenseOutcome:
    if kind not in CAR_EXPENSE_KINDS:
        raise CarEntryError(f"未知养车类型: {kind}")
    if len(idempotency_key) < MIN_IDEMPOTENCY_KEY_LENGTH:
        raise CarEntryError(
            f"idempotency_key 至少 {MIN_IDEMPOTENCY_KEY_LENGTH} 位"
        )
    timestamp = occurred_at or now or datetime.now()
    if kind == CAR_MILEAGE_KIND and odometer_km is None:
        raise CarEntryError("里程记录必须带 odometer_km")
    if kind != CAR_MILEAGE_KIND and (amount_minor is None or amount_minor <= 0):
        raise CarEntryError("amount_minor 必须为正整数分")
    odometer_delta = _apply_odometer(user_id, odometer_km, now=now)

    if kind == CAR_MILEAGE_KIND:
        log = car_repository.create_mileage_log(
            user_id,
            CarMileageLogDraft(
                odometer_km=odometer_km,
                delta_km=odometer_delta,
                recorded_at=timestamp,
                note=note,
            ),
            now=now,
        )
        return CarExpenseOutcome(
            kind=kind,
            entry_id=None,
            record_id=log.id,
            category_id=None,
            category_name="",
            normalized_from=None,
            odometer_delta_km=odometer_delta,
            hint=MILEAGE_HINT,
        )

    category_name = KIND_CATEGORY_NAMES[kind]
    account_id = ledger_service.resolve_account_id(user_id)
    normalization = ledger_category.normalize(user_id, category_name, now=now)
    draft = LedgerEntryDraft(
        user_id=user_id,
        account_id=account_id,
        category_id=normalization.category_id,
        amount_minor=amount_minor,
        direction="expense",
        occurred_at=timestamp,
        merchant=place,
        note=note,
        source=source,
        source_ref=f"{CAR_SOURCE_REF_PREFIX}:{kind}",
        idempotency_key=idempotency_key,
    )
    outcome = ledger_service.record_entry(
        draft, idempotency_key=idempotency_key, now=now
    )
    entry = outcome.entry
    record_id: str | None = None
    if kind == "service":
        try:
            record = car_repository.create_service_record(
                user_id,
                CarServiceRecordDraft(
                    title=note or category_name,
                    place=place,
                    odometer_km=odometer_km,
                    occurred_at=timestamp,
                    amount_minor=amount_minor,
                    ledger_entry_id=entry.id,
                ),
                now=now,
            )
        except Exception as exc:
            _rollback_entry(
                entry.id,
                created=outcome.created,
                idempotency_key=idempotency_key,
                now=now,
            )
            raise CarEntryError("保养档案写入失败，账目已回滚") from exc
        record_id = record.id
    return CarExpenseOutcome(
        kind=kind,
        entry_id=entry.id,
        record_id=record_id,
        category_id=normalization.category_id,
        category_name=normalization.category_name,
        normalized_from=normalization.reason,
        odometer_delta_km=odometer_delta,
        hint=LINKAGE_HINT,
    )
