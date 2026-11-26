from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.core import timeutil
from app.core.settings import get_settings
from app.models.car import CarReminder
from app.repositories import car_repository
from app.services.car import aggregate as car_aggregate
from app.services.car import reminders as car_reminders
from app.services.ledger import query as ledger_query

EV_METRICS_BASIS = "approximate"
EV_METRICS_NOTE = "充电度数本期未结构化存储，电耗精算列 V2（当前按充电费用近似）"
UPCOMING_SERVICE_ID = "car-next-service"

INSURANCE_KEY = "insurance"
INSPECTION_KEY = "inspection"
CHARGER_KEY = "charger"
SERVICE_INTERVAL_KEY = "service_interval"

EMPTY_VALUE_TEXT = "未填写"

logger = logging.getLogger(__name__)


class CarProfileValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CarLoanView:
    remaining_minor: int
    monthly_minor: int
    paid_periods: int
    total_periods: int
    next_due_at: datetime | None
    settled_at: datetime | None
    paid_ratio: float


@dataclass(frozen=True, slots=True)
class CarIdentityView:
    model: str | None
    plate: str | None
    trim_note: str | None
    battery_kwh: float | None
    age_text: str | None
    purchased_at: datetime | None
    odometer_km: int


@dataclass(frozen=True, slots=True)
class CarFileView:
    key: str
    label: str
    detail: str | None
    value_text: str
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CarServiceRowView:
    id: str
    title: str
    place: str | None
    occurred_at: datetime | None
    amount_minor: int | None
    odometer_km: int | None
    upcoming: bool
    due_at: datetime | None = None
    due_km: int | None = None


@dataclass(frozen=True, slots=True)
class CarEvMetricsView:
    odometer_km: int | None
    odometer_delta_month: int
    charge_cost_minor_month: int
    charge_count_month: int
    charge_kwh_month: float | None
    kwh_per_100km: float | None
    basis: str
    note: str


@dataclass(frozen=True, slots=True)
class CarOverview:
    profile: Mapping[str, Any] | None
    loan: CarLoanView | None
    ev_metrics: CarEvMetricsView
    expense_breakdown: tuple[car_aggregate.CarExpenseLine, ...]
    expense_total_minor: int
    reminders: tuple[CarReminder, ...]
    restriction_guide: str | None
    recent_records: tuple[car_aggregate.CarRecentRecord, ...]
    degraded_blocks: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class CarProfileView:
    identity: CarIdentityView | None
    files: tuple[CarFileView, ...]
    loan: CarLoanView | None
    services: tuple[CarServiceRowView, ...]
    reminders: tuple[CarReminder, ...]
    restriction_guide: str | None


def loan_view(row) -> CarLoanView | None:
    if row is None:
        return None
    total = int(row.total_periods)
    paid = int(row.paid_periods)
    return CarLoanView(
        remaining_minor=int(row.monthly_minor) * max(0, total - paid),
        monthly_minor=int(row.monthly_minor),
        paid_periods=paid,
        total_periods=total,
        next_due_at=row.next_due_at,
        settled_at=row.settled_at,
        paid_ratio=(paid / total) if total else 0.0,
    )


def _identity(profile, now: datetime) -> CarIdentityView | None:
    if profile is None:
        return None
    return CarIdentityView(
        model=profile.model,
        plate=profile.plate,
        trim_note=profile.trim_note,
        battery_kwh=profile.battery_kwh,
        age_text=car_reminders.age_text(profile.purchased_at, now),
        purchased_at=profile.purchased_at,
        odometer_km=int(profile.odometer_km),
    )


def _files(profile) -> tuple[CarFileView, ...]:
    if profile is None:
        return ()
    insurance = profile.insurance_due_at
    inspection = profile.inspection_due_at
    power = profile.charger_power_kw
    interval_km = profile.service_interval_km
    interval_months = profile.service_interval_months
    if interval_km and interval_months:
        interval_text = f"每 {int(interval_km):,} km 或 {int(interval_months)} 个月"
    elif interval_km:
        interval_text = f"每 {int(interval_km):,} km"
    elif interval_months:
        interval_text = f"每 {int(interval_months)} 个月"
    else:
        interval_text = EMPTY_VALUE_TEXT
    return (
        CarFileView(
            key=INSURANCE_KEY,
            label="车辆保险",
            detail=profile.insurance_note,
            value_text=f"{insurance:%Y-%m-%d} 到期" if insurance else EMPTY_VALUE_TEXT,
            due_at=insurance,
        ),
        CarFileView(
            key=INSPECTION_KEY,
            label="年检",
            detail=profile.inspection_note,
            value_text=(
                f"{inspection:%Y 年 %m 月}" if inspection else EMPTY_VALUE_TEXT
            ),
            due_at=inspection,
        ),
        CarFileView(
            key=CHARGER_KEY,
            label="家用充电桩",
            detail=profile.charger_note,
            value_text=f"{power:g} kW" if power else EMPTY_VALUE_TEXT,
        ),
        CarFileView(
            key=SERVICE_INTERVAL_KEY,
            label="保养周期",
            detail=None,
            value_text=interval_text,
        ),
    )


def _ev_metrics(profile, breakdown, user_id: str, *, now: datetime) -> CarEvMetricsView:
    window = ledger_query.Period.month(now)
    delta_month = 0
    for log in car_repository.list_mileage_logs(user_id):
        if window.since <= log.recorded_at < window.until and log.delta_km:
            delta_month += int(log.delta_km)
    charge = next(
        (line for line in breakdown if line.category_name == "充电"),
        None,
    )
    return CarEvMetricsView(
        odometer_km=int(profile.odometer_km) if profile is not None else None,
        odometer_delta_month=delta_month,
        charge_cost_minor_month=charge.net_minor if charge else 0,
        charge_count_month=charge.count if charge else 0,
        charge_kwh_month=None,
        kwh_per_100km=None,
        basis=EV_METRICS_BASIS,
        note=EV_METRICS_NOTE,
    )


def _service_timeline(
    user_id: str,
    bundle: car_reminders.ReminderBundle,
    *,
    limit: int | None = None,
) -> tuple[CarServiceRowView, ...]:
    rows = [
        CarServiceRowView(
            id=record.id,
            title=record.title,
            place=record.place,
            occurred_at=record.occurred_at,
            amount_minor=record.amount_minor,
            odometer_km=record.odometer_km,
            upcoming=False,
        )
        for record in car_repository.list_service_records(user_id, limit=limit)
    ]
    upcoming = next(
        (item for item in bundle.reminders if item.kind == car_reminders.SERVICE_KIND),
        None,
    )
    if upcoming is not None:
        rows.append(
            CarServiceRowView(
                id=UPCOMING_SERVICE_ID,
                title=upcoming.title,
                place=None,
                occurred_at=None,
                amount_minor=None,
                odometer_km=None,
                upcoming=True,
                due_at=upcoming.due_at,
                due_km=upcoming.due_km,
            )
        )
    return tuple(rows)


def _reminder_bundle(user_id: str, profile, now: datetime):
    latest = car_repository.list_service_records(user_id, limit=1)
    return car_reminders.derive(
        profile=profile,
        last_service=latest[0] if latest else None,
        now=now,
        settings=get_settings(),
    )


def reminders(user_id: str, *, now: datetime | None = None) -> tuple[CarReminder, ...]:
    """只读面的活跃提醒（简报等聚合用）：无档案或读取失败返回空，调用方省卡。"""
    try:
        moment = timeutil.ensure_aware(now) or timeutil.now()
        profile = car_repository.get_profile(user_id)
        if profile is None:
            return ()
        return _reminder_bundle(user_id, profile, moment).reminders
    except Exception as error:
        logger.warning(
            "车辆提醒读取失败: %s: %s",
            error.__class__.__name__,
            error,
        )
        return ()


def overview(user_id: str, *, now: datetime | None = None) -> CarOverview:
    moment = timeutil.ensure_aware(now) or timeutil.now()
    degraded: list[str] = []
    profile = car_repository.get_profile(user_id)
    try:
        loan = loan_view(car_repository.get_loan(user_id))
    except Exception:
        loan = None
        degraded.append("loan")
    try:
        breakdown = tuple(
            car_aggregate.car_expense_breakdown(user_id, now=moment)
        )
    except Exception:
        breakdown = ()
        degraded.append("expense_breakdown")
    try:
        recent = tuple(car_aggregate.car_recent_records(user_id, limit=10))
    except Exception:
        recent = ()
        degraded.append("recent_records")
    try:
        bundle = _reminder_bundle(user_id, profile, moment)
    except Exception:
        bundle = car_reminders.ReminderBundle(reminders=(), restriction_configured=False, guide=None)
        degraded.append("reminders")
    return CarOverview(
        profile=(
            {
                "model": profile.model,
                "plate": profile.plate,
                "odometer_km": int(profile.odometer_km),
            }
            if profile is not None
            else None
        ),
        loan=loan,
        ev_metrics=_ev_metrics(profile, breakdown, user_id, now=moment),
        expense_breakdown=breakdown,
        expense_total_minor=car_aggregate.car_expense_total(list(breakdown)),
        reminders=bundle.reminders,
        restriction_guide=bundle.guide,
        recent_records=recent,
        degraded_blocks=tuple(degraded),
    )


def profile_detail(
    user_id: str, *, now: datetime | None = None, limit: int = 50
) -> CarProfileView:
    moment = timeutil.ensure_aware(now) or timeutil.now()
    profile = car_repository.get_profile(user_id)
    bundle = _reminder_bundle(user_id, profile, moment)
    return CarProfileView(
        identity=_identity(profile, moment),
        files=_files(profile),
        loan=loan_view(car_repository.get_loan(user_id)),
        services=_service_timeline(user_id, bundle, limit=limit),
        reminders=bundle.reminders,
        restriction_guide=bundle.guide,
    )


def list_services(
    user_id: str, *, limit: int = 50, now: datetime | None = None
) -> tuple[int, tuple[CarServiceRowView, ...]]:
    moment = timeutil.ensure_aware(now) or timeutil.now()
    profile = car_repository.get_profile(user_id)
    bundle = _reminder_bundle(user_id, profile, moment)
    total = len(car_repository.list_service_records(user_id))
    rows = _service_timeline(user_id, bundle, limit=limit)
    return total, rows


def update_profile(
    user_id: str,
    *,
    profile_values: Mapping[str, Any] | None = None,
    loan_values: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    moment = timeutil.ensure_aware(now) or timeutil.now()
    if loan_values:
        current = car_repository.get_loan(user_id)
        merged = {
            "monthly_minor": current.monthly_minor if current else None,
            "paid_periods": current.paid_periods if current else 0,
            "total_periods": current.total_periods if current else None,
            "principal_minor": current.principal_minor if current else None,
        }
        merged.update(loan_values)
        if not merged["total_periods"] or int(merged["total_periods"]) <= 0:
            raise CarProfileValidationError("total_periods 必须为正")
        if not merged["monthly_minor"] or int(merged["monthly_minor"]) <= 0:
            raise CarProfileValidationError("monthly_minor 必须为正")
        if int(merged["paid_periods"]) > int(merged["total_periods"]):
            raise CarProfileValidationError("paid_periods 不得超过 total_periods")
    if profile_values:
        car_repository.upsert_profile(user_id, profile_values, now=moment)
    if loan_values:
        car_repository.upsert_loan(user_id, loan_values, now=moment)
