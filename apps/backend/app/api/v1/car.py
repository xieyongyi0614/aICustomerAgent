"""车辆域产品级 API：只做表现，零仓储与 LLM 依赖（同 ledger.py 先例）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.auth import require_user
from app.services.car import entries as car_entries
from app.services.car import service as car_service
from app.services.ledger import format as format_service

car_router = APIRouter(prefix="/car", tags=["car"])

LIMIT_DEFAULT = 20
LIMIT_MAX = 50

PROFILE_VALUE_KEYS = (
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
)
RESTRICTION_VALUE_KEYS = (
    "restriction_city",
    "restriction_digits",
    "restriction_weekday",
)
RESTRICTION_FROM_REQUEST = {
    "city": "restriction_city",
    "digits": "restriction_digits",
    "weekday": "restriction_weekday",
}


class CarLoanOut(BaseModel):
    remaining_minor: int
    remaining_text: str
    monthly_minor: int
    monthly_text: str
    paid_periods: int
    total_periods: int
    paid_ratio: float
    next_due_at: str | None = None
    settled_at: str | None = None


class CarProfileSummaryOut(BaseModel):
    model: str | None = None
    plate: str | None = None
    odometer_km: int


class CarExpenseLineOut(BaseModel):
    category_id: str | None = None
    category_name: str
    net_minor: int
    net_text: str
    count: int


class CarRecentRecordOut(BaseModel):
    kind: str
    title: str
    subtitle: str | None = None
    net_minor: int | None = None
    odometer_delta_km: int | None = None
    occurred_at: str
    source: str
    ledger_entry_id: str | None = None


class CarReminderOut(BaseModel):
    kind: str
    title: str
    detail: str
    due_at: str | None = None
    due_km: int | None = None
    level: str = "normal"


class CarEvMetricsOut(BaseModel):
    odometer_km: int | None = None
    odometer_delta_month: int
    charge_cost_minor_month: int
    charge_cost_text_month: str
    charge_count_month: int
    charge_kwh_month: float | None = None
    kwh_per_100km: float | None = None
    basis: str
    note: str


class CarOverviewOut(BaseModel):
    profile: CarProfileSummaryOut | None = None
    loan: CarLoanOut | None = None
    ev_metrics: CarEvMetricsOut
    expense_breakdown: list[CarExpenseLineOut]
    expense_total_minor: int
    expense_total_text: str
    reminders: list[CarReminderOut]
    restriction_guide: str | None = None
    recent_records: list[CarRecentRecordOut]
    degraded_blocks: list[str]


class CarIdentityOut(BaseModel):
    model: str | None = None
    plate: str | None = None
    trim_note: str | None = None
    battery_kwh: float | None = None
    age_text: str | None = None
    purchased_at: str | None = None
    odometer_km: int


class CarFileOut(BaseModel):
    key: str
    label: str
    detail: str | None = None
    value_text: str
    due_at: str | None = None


class CarServiceRowOut(BaseModel):
    id: str
    title: str
    place: str | None = None
    occurred_at: str | None = None
    amount_minor: int | None = None
    amount_text: str | None = None
    odometer_km: int | None = None
    upcoming: bool
    due_at: str | None = None
    due_km: int | None = None


class CarProfileOut(BaseModel):
    identity: CarIdentityOut | None = None
    files: list[CarFileOut]
    loan: CarLoanOut | None = None
    services: list[CarServiceRowOut]
    reminders: list[CarReminderOut]
    restriction_guide: str | None = None


class CarServiceListOut(BaseModel):
    total: int
    limit: int
    items: list[CarServiceRowOut]


class CarRestrictionRequest(BaseModel):
    city: str | None = Field(default=None, max_length=40)
    digits: str | None = Field(default=None, max_length=40)
    weekday: str | None = Field(default=None, max_length=20)


class CarLoanRequest(BaseModel):
    principal_minor: int | None = Field(default=None, ge=0)
    monthly_minor: int | None = Field(default=None, gt=0)
    paid_periods: int | None = Field(default=None, ge=0)
    total_periods: int | None = Field(default=None, gt=0)
    next_due_at: datetime | None = None
    settled_at: datetime | None = None


class CarProfileUpdateRequest(BaseModel):
    model: str | None = Field(default=None, max_length=120)
    plate: str | None = Field(default=None, max_length=32)
    trim_note: str | None = Field(default=None, max_length=120)
    battery_kwh: float | None = Field(default=None, gt=0)
    purchased_at: datetime | None = None
    odometer_km: int | None = Field(default=None, ge=0)
    insurance_due_at: datetime | None = None
    insurance_note: str | None = Field(default=None, max_length=120)
    insurance_annual_minor: int | None = Field(default=None, ge=0)
    inspection_due_at: datetime | None = None
    inspection_note: str | None = Field(default=None, max_length=120)
    charger_power_kw: float | None = Field(default=None, gt=0)
    charger_note: str | None = Field(default=None, max_length=120)
    service_interval_km: int | None = Field(default=None, gt=0)
    service_interval_months: int | None = Field(default=None, gt=0)
    restriction: CarRestrictionRequest | None = None
    loan: CarLoanRequest | None = None


class CarEntryCreateRequest(BaseModel):
    kind: Literal["charge", "fuel", "mileage", "parking", "toll", "service"]
    amount_minor: int | None = Field(default=None, gt=0)
    occurred_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)
    odometer_km: int | None = Field(default=None, ge=0)
    place: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=64)


class CarEntryOut(BaseModel):
    kind: str
    entry_id: str | None = None
    record_id: str | None = None
    category_id: str | None = None
    category_name: str
    normalized_from: str | None = None
    odometer_delta_km: int | None = None
    hint: str


def _money(minor: int) -> str:
    return format_service.format_minor(int(minor))


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _loan_out(loan) -> CarLoanOut | None:
    if loan is None:
        return None
    return CarLoanOut(
        remaining_minor=loan.remaining_minor,
        remaining_text=_money(loan.remaining_minor),
        monthly_minor=loan.monthly_minor,
        monthly_text=_money(loan.monthly_minor),
        paid_periods=loan.paid_periods,
        total_periods=loan.total_periods,
        paid_ratio=loan.paid_ratio,
        next_due_at=_dt(loan.next_due_at),
        settled_at=_dt(loan.settled_at),
    )


def _reminder_out(item) -> CarReminderOut:
    return CarReminderOut(
        kind=item.kind,
        title=item.title,
        detail=item.detail,
        due_at=_dt(item.due_at),
        due_km=item.due_km,
        level=item.level,
    )


def _service_row_out(item) -> CarServiceRowOut:
    return CarServiceRowOut(
        id=item.id,
        title=item.title,
        place=item.place,
        occurred_at=_dt(item.occurred_at),
        amount_minor=item.amount_minor,
        amount_text=_money(item.amount_minor) if item.amount_minor else None,
        odometer_km=item.odometer_km,
        upcoming=item.upcoming,
        due_at=_dt(item.due_at),
        due_km=item.due_km,
    )


def _profile_out(view: car_service.CarProfileView) -> CarProfileOut:
    identity = None
    if view.identity is not None:
        identity = CarIdentityOut(
            model=view.identity.model,
            plate=view.identity.plate,
            trim_note=view.identity.trim_note,
            battery_kwh=view.identity.battery_kwh,
            age_text=view.identity.age_text,
            purchased_at=_dt(view.identity.purchased_at),
            odometer_km=view.identity.odometer_km,
        )
    return CarProfileOut(
        identity=identity,
        files=[
            CarFileOut(
                key=row.key,
                label=row.label,
                detail=row.detail,
                value_text=row.value_text,
                due_at=_dt(row.due_at),
            )
            for row in view.files
        ],
        loan=_loan_out(view.loan),
        services=[_service_row_out(row) for row in view.services],
        reminders=[_reminder_out(item) for item in view.reminders],
        restriction_guide=view.restriction_guide,
    )


@car_router.get("/overview", response_model=CarOverviewOut)
def get_overview(user_id: str = Depends(require_user)):
    view = car_service.overview(user_id)
    metrics = view.ev_metrics
    return CarOverviewOut(
        profile=(
            CarProfileSummaryOut(**dict(view.profile)) if view.profile else None
        ),
        loan=_loan_out(view.loan),
        ev_metrics=CarEvMetricsOut(
            odometer_km=metrics.odometer_km,
            odometer_delta_month=metrics.odometer_delta_month,
            charge_cost_minor_month=metrics.charge_cost_minor_month,
            charge_cost_text_month=_money(metrics.charge_cost_minor_month),
            charge_count_month=metrics.charge_count_month,
            charge_kwh_month=metrics.charge_kwh_month,
            kwh_per_100km=metrics.kwh_per_100km,
            basis=metrics.basis,
            note=metrics.note,
        ),
        expense_breakdown=[
            CarExpenseLineOut(
                category_id=line.category_id,
                category_name=line.category_name,
                net_minor=line.net_minor,
                net_text=_money(line.net_minor),
                count=line.count,
            )
            for line in view.expense_breakdown
        ],
        expense_total_minor=view.expense_total_minor,
        expense_total_text=_money(view.expense_total_minor),
        reminders=[_reminder_out(item) for item in view.reminders],
        restriction_guide=view.restriction_guide,
        recent_records=[
            CarRecentRecordOut(
                kind=record.kind,
                title=record.title,
                subtitle=record.subtitle,
                net_minor=record.net_minor,
                odometer_delta_km=record.odometer_delta_km,
                occurred_at=record.occurred_at.isoformat(),
                source=record.source,
                ledger_entry_id=record.ledger_entry_id,
            )
            for record in view.recent_records
        ],
        degraded_blocks=list(view.degraded_blocks),
    )


@car_router.get("/profile", response_model=CarProfileOut)
def get_profile(user_id: str = Depends(require_user)):
    return _profile_out(car_service.profile_detail(user_id))


@car_router.put("/profile", response_model=CarProfileOut)
def update_profile(
    body: CarProfileUpdateRequest,
    user_id: str = Depends(require_user),
):
    payload = body.model_dump(exclude_unset=True)
    restriction = payload.pop("restriction", None)
    loan_values = payload.pop("loan", None)
    profile_values = {
        key: value for key, value in payload.items() if key in PROFILE_VALUE_KEYS
    }
    if restriction is not None:
        for source, target in RESTRICTION_FROM_REQUEST.items():
            if source in restriction:
                profile_values[target] = restriction[source]
    try:
        car_service.update_profile(
            user_id,
            profile_values=profile_values,
            loan_values=loan_values,
        )
    except car_service.CarProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)[:120]) from exc
    return _profile_out(car_service.profile_detail(user_id))


@car_router.post("/entries", response_model=CarEntryOut)
def create_entry(
    body: CarEntryCreateRequest,
    user_id: str = Depends(require_user),
):
    try:
        outcome = car_entries.record_car_expense(
            user_id,
            kind=body.kind,
            amount_minor=body.amount_minor,
            occurred_at=body.occurred_at,
            note=body.note,
            odometer_km=body.odometer_km,
            place=body.place,
            idempotency_key=body.idempotency_key,
        )
    except car_entries.CarEntryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:120]) from exc
    return CarEntryOut(
        kind=outcome.kind,
        entry_id=outcome.entry_id,
        record_id=outcome.record_id,
        category_id=outcome.category_id,
        category_name=outcome.category_name,
        normalized_from=outcome.normalized_from,
        odometer_delta_km=outcome.odometer_delta_km,
        hint=outcome.hint,
    )


@car_router.get("/services", response_model=CarServiceListOut)
def list_services(
    limit: int = Query(default=LIMIT_DEFAULT, ge=1),
    user_id: str = Depends(require_user),
):
    if limit > LIMIT_MAX:
        raise HTTPException(status_code=400, detail=f"limit 不能超过 {LIMIT_MAX}")
    total, rows = car_service.list_services(user_id, limit=limit)
    return CarServiceListOut(
        total=total,
        limit=limit,
        items=[_service_row_out(row) for row in rows],
    )
