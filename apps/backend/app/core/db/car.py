from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class CarProfileRow(Base):
    __tablename__ = "car_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    plate: Mapped[str | None] = mapped_column(String, nullable=True)
    trim_note: Mapped[str | None] = mapped_column(String, nullable=True)
    battery_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    odometer_km: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    insurance_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    insurance_note: Mapped[str | None] = mapped_column(String, nullable=True)
    insurance_annual_minor: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    inspection_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    inspection_note: Mapped[str | None] = mapped_column(String, nullable=True)
    charger_power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    charger_note: Mapped[str | None] = mapped_column(String, nullable=True)
    service_interval_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_interval_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    restriction_city: Mapped[str | None] = mapped_column(String, nullable=True)
    restriction_digits: Mapped[str | None] = mapped_column(String, nullable=True)
    restriction_weekday: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_car_profiles_user"),
        CheckConstraint("odometer_km >= 0", name="ck_car_profiles_odometer_km"),
        CheckConstraint(
            "battery_kwh IS NULL OR battery_kwh > 0",
            name="ck_car_profiles_battery_kwh",
        ),
        CheckConstraint(
            "charger_power_kw IS NULL OR charger_power_kw > 0",
            name="ck_car_profiles_charger_power_kw",
        ),
        CheckConstraint(
            "service_interval_km IS NULL OR service_interval_km > 0",
            name="ck_car_profiles_service_interval_km",
        ),
        CheckConstraint(
            "service_interval_months IS NULL OR service_interval_months > 0",
            name="ck_car_profiles_service_interval_months",
        ),
        CheckConstraint(
            "insurance_annual_minor IS NULL OR insurance_annual_minor >= 0",
            name="ck_car_profiles_insurance_annual_minor",
        ),
    )


class CarLoanRow(Base):
    __tablename__ = "car_loans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    principal_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_minor: Mapped[int | None] = mapped_column(Integer, nullable=False)
    paid_periods: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_periods: Mapped[int] = mapped_column(Integer, nullable=False)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_car_loans_user"),
        CheckConstraint("monthly_minor > 0", name="ck_car_loans_monthly_minor"),
        CheckConstraint("total_periods > 0", name="ck_car_loans_total_periods"),
        CheckConstraint(
            "paid_periods >= 0 AND paid_periods <= total_periods",
            name="ck_car_loans_periods",
        ),
    )


class CarServiceRecordRow(Base):
    __tablename__ = "car_service_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    place: Mapped[str | None] = mapped_column(String, nullable=True)
    odometer_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_due_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ledger_entry_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "odometer_km IS NULL OR odometer_km >= 0",
            name="ck_car_service_records_odometer_km",
        ),
        CheckConstraint(
            "amount_minor IS NULL OR amount_minor > 0",
            name="ck_car_service_records_amount_minor",
        ),
        Index("ix_car_service_records_user_time", "user_id", "occurred_at"),
    )


class CarMileageLogRow(Base):
    __tablename__ = "car_mileage_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    odometer_km: Mapped[int] = mapped_column(Integer, nullable=False)
    delta_km: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("odometer_km >= 0", name="ck_car_mileage_logs_odometer_km"),
        CheckConstraint(
            "delta_km IS NULL OR delta_km >= 0", name="ck_car_mileage_logs_delta_km"
        ),
        Index("ix_car_mileage_logs_user_time", "user_id", "recorded_at"),
    )
