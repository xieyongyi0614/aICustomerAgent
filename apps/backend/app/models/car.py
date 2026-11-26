from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CarExpenseKind = Literal["charge", "fuel", "mileage", "parking", "toll", "service"]
CarReminderKind = Literal["service", "insurance", "inspection", "restriction"]
CarReminderLevel = Literal["normal", "soon"]

CAR_EXPENSE_KINDS: tuple[str, ...] = (
    "charge",
    "fuel",
    "mileage",
    "parking",
    "toll",
    "service",
)
CAR_MILEAGE_KIND = "mileage"


class CarProfile(BaseModel):
    id: str
    user_id: str
    model: str | None = None
    plate: str | None = None
    trim_note: str | None = None
    battery_kwh: float | None = None
    purchased_at: datetime | None = None
    odometer_km: int = 0
    insurance_due_at: datetime | None = None
    insurance_note: str | None = None
    insurance_annual_minor: int | None = None
    inspection_due_at: datetime | None = None
    inspection_note: str | None = None
    charger_power_kw: float | None = None
    charger_note: str | None = None
    service_interval_km: int | None = None
    service_interval_months: int | None = None
    restriction_city: str | None = None
    restriction_digits: str | None = None
    restriction_weekday: str | None = None
    created_at: datetime
    updated_at: datetime


class CarProfileDraft(BaseModel):
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
    restriction_city: str | None = Field(default=None, max_length=40)
    restriction_digits: str | None = Field(default=None, max_length=40)
    restriction_weekday: str | None = Field(default=None, max_length=20)


class CarLoan(BaseModel):
    id: str
    user_id: str
    principal_minor: int | None = None
    monthly_minor: int
    paid_periods: int = 0
    total_periods: int
    next_due_at: datetime | None = None
    settled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CarLoanDraft(BaseModel):
    principal_minor: int | None = Field(default=None, ge=0)
    monthly_minor: int = Field(gt=0)
    paid_periods: int = Field(default=0, ge=0)
    total_periods: int = Field(gt=0)
    next_due_at: datetime | None = None
    settled_at: datetime | None = None

    @model_validator(mode="after")
    def _periods_within_total(self) -> "CarLoanDraft":
        if self.paid_periods > self.total_periods:
            raise ValueError("paid_periods 不得超过 total_periods")
        return self


class CarServiceRecord(BaseModel):
    id: str
    user_id: str
    title: str
    place: str | None = None
    odometer_km: int | None = None
    occurred_at: datetime
    amount_minor: int | None = None
    next_due_at: datetime | None = None
    next_due_km: int | None = None
    ledger_entry_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CarServiceRecordDraft(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    place: str | None = Field(default=None, max_length=120)
    odometer_km: int | None = Field(default=None, ge=0)
    occurred_at: datetime
    amount_minor: int | None = Field(default=None, gt=0)
    next_due_at: datetime | None = None
    next_due_km: int | None = Field(default=None, ge=0)
    ledger_entry_id: str | None = None


class CarMileageLog(BaseModel):
    id: str
    user_id: str
    odometer_km: int
    delta_km: int | None = None
    recorded_at: datetime
    note: str | None = None
    created_at: datetime
    updated_at: datetime


class CarMileageLogDraft(BaseModel):
    odometer_km: int = Field(ge=0)
    delta_km: int | None = Field(default=None, ge=0)
    recorded_at: datetime
    note: str | None = Field(default=None, max_length=120)


class CarReminder(BaseModel):
    kind: CarReminderKind
    title: str
    detail: str
    due_at: datetime | None = None
    due_km: int | None = None
    level: CarReminderLevel = "normal"
